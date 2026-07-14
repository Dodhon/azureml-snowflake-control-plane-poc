"""Narrow Azure ML SDK v2 gateway for model selection and batch inference."""

from __future__ import annotations

import re
import shutil
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from azureml_snowflake_poc.configuration import require
from azureml_snowflake_poc.gate import (
    GateDecision,
    MetricRule,
    PromotionOutcome,
    evaluate_promotion,
)

_MODEL_ID = re.compile(r"/models/(?P<name>[^/]+)/versions/(?P<version>[^/]+)$", re.IGNORECASE)
_NAME = re.compile(r"[^a-z0-9-]+")


class ConcurrentPromotionError(RuntimeError):
    """The production deployment changed between gate read and endpoint update."""


@dataclass(frozen=True, slots=True)
class ProductionDeployment:
    endpoint_name: str
    deployment_name: str
    model_name: str
    model_version: str
    metrics: dict[str, float]
    mapping_version: str
    mlflow_run_id: str


@dataclass(frozen=True, slots=True)
class ModelSelection:
    candidate_name: str
    candidate_version: str
    decision: GateDecision
    selected: ProductionDeployment | None

    def to_dict(self) -> dict[str, object]:
        return {
            "candidate_name": self.candidate_name,
            "candidate_version": self.candidate_version,
            "decision": self.decision.to_dict(),
            "selected": (
                {
                    "endpoint_name": self.selected.endpoint_name,
                    "deployment_name": self.selected.deployment_name,
                    "model_name": self.selected.model_name,
                    "model_version": self.selected.model_version,
                    "metrics": self.selected.metrics,
                    "mapping_version": self.selected.mapping_version,
                    "mlflow_run_id": self.selected.mlflow_run_id,
                }
                if self.selected is not None
                else None
            ),
        }


class AzureMLGateway:
    """Azure SDK adapter; business policy stays in dependency-light modules."""

    def __init__(self, ml_client: Any, *, retraining_pipeline: Path | None = None) -> None:
        self._client = ml_client
        self._retraining_pipeline = retraining_pipeline

    @classmethod
    def from_environment(cls, *, retraining_pipeline: Path | None = None) -> AzureMLGateway:
        import os

        from azure.ai.ml import MLClient
        from azure.identity import DefaultAzureCredential

        required = {
            name: os.environ.get(name)
            for name in ("AZURE_SUBSCRIPTION_ID", "AZURE_RESOURCE_GROUP", "AZUREML_WORKSPACE_NAME")
        }
        missing = [name for name, value in required.items() if not value]
        if missing:
            raise RuntimeError(f"missing Azure environment variables: {', '.join(missing)}")
        client = MLClient(
            DefaultAzureCredential(),
            required["AZURE_SUBSCRIPTION_ID"],
            required["AZURE_RESOURCE_GROUP"],
            required["AZUREML_WORKSPACE_NAME"],
        )
        return cls(client, retraining_pipeline=retraining_pipeline)

    @classmethod
    def from_config(cls, config: Mapping[str, Any]) -> AzureMLGateway:
        """Build a workspace client from the explicit pipeline configuration."""
        from azure.ai.ml import MLClient
        from azure.identity import DefaultAzureCredential

        return cls(
            MLClient(
                DefaultAzureCredential(),
                require(config, "azure.subscription_id"),
                require(config, "azure.resource_group"),
                require(config, "azure.workspace_name"),
            )
        )

    @staticmethod
    def _model_identity(model_reference: object) -> tuple[str, str]:
        value = getattr(model_reference, "id", model_reference)
        match = _MODEL_ID.search(str(value))
        if not match:
            raise RuntimeError(f"cannot parse exact model identity from deployment: {value!r}")
        return match.group("name"), match.group("version")

    def _production_deployment(self, endpoint_name: str) -> ProductionDeployment | None:
        from azure.core.exceptions import ResourceNotFoundError

        try:
            endpoint = self._client.batch_endpoints.get(endpoint_name)
        except ResourceNotFoundError:
            return None
        deployment_name = getattr(getattr(endpoint, "defaults", None), "deployment_name", None)
        if not deployment_name:
            return None
        deployment = self._client.batch_deployments.get(
            name=deployment_name,
            endpoint_name=endpoint_name,
        )
        model_name, model_version = self._model_identity(deployment.model)
        model = self._client.models.get(name=model_name, version=model_version)
        metrics: dict[str, float] = {}
        for key, value in (model.tags or {}).items():
            if key.startswith("metric_"):
                try:
                    metrics[key.removeprefix("metric_")] = float(value)
                except (TypeError, ValueError):
                    continue
        model_tags = model.tags or {}
        mapping_version = model_tags.get("quantity_class_mapping_version")
        mlflow_run_id = model_tags.get("mlflow_run_id")
        if not mapping_version or not mlflow_run_id:
            raise RuntimeError(
                "production model is missing quantity mapping or MLflow run provenance"
            )
        return ProductionDeployment(
            endpoint_name=endpoint_name,
            deployment_name=deployment_name,
            model_name=model_name,
            model_version=model_version,
            metrics=metrics,
            mapping_version=str(mapping_version),
            mlflow_run_id=str(mlflow_run_id),
        )

    def register_and_select(
        self,
        *,
        model_path: Path,
        model_name: str,
        candidate_version: str,
        candidate_metrics: dict[str, float],
        metadata: dict[str, str],
        rules: tuple[MetricRule, ...],
        endpoint_name: str,
        compute_name: str,
        environment_name: str,
        scoring_code: Path,
    ) -> ModelSelection:
        """Register every candidate, then gate and optimistically switch the endpoint default."""
        from azure.ai.ml.constants import AssetTypes, BatchDeploymentOutputAction
        from azure.ai.ml.entities import (
            BatchEndpoint,
            BatchRetrySettings,
            CodeConfiguration,
            Model,
            ModelBatchDeployment,
            ModelBatchDeploymentSettings,
        )
        from azure.core.exceptions import ResourceNotFoundError

        tags = {
            **metadata,
            **{
                f"metric_{name}": format(value, ".12g") for name, value in candidate_metrics.items()
            },
            "lifecycle": "candidate",
        }
        candidate = self._client.models.create_or_update(
            Model(
                name=model_name,
                version=candidate_version,
                path=str(model_path),
                type=AssetTypes.MLFLOW_MODEL,
                tags=tags,
            )
        )
        production = self._production_deployment(endpoint_name)
        candidate_mapping = metadata.get("quantity_class_mapping_version")
        if not candidate_mapping:
            raise ValueError("candidate metadata is missing quantity_class_mapping_version")
        if production is not None and production.mapping_version != candidate_mapping:
            decision = GateDecision(
                outcome=PromotionOutcome.HALT,
                reasons=(
                    "candidate and production quantity class mapping versions differ: "
                    f"{candidate_mapping!r} != {production.mapping_version!r}",
                ),
                candidate_metrics=dict(candidate_metrics),
                champion_metrics=dict(production.metrics),
            )
            return ModelSelection(candidate.name, candidate.version, decision, None)
        decision = evaluate_promotion(
            candidate_metrics,
            production.metrics if production else None,
            rules,
            has_production_deployment=production is not None,
        )
        if decision.outcome is PromotionOutcome.HALT:
            return ModelSelection(candidate.name, candidate.version, decision, None)
        if decision.outcome is PromotionOutcome.RETAIN:
            assert production is not None
            return ModelSelection(candidate.name, candidate.version, decision, production)

        try:
            endpoint = self._client.batch_endpoints.get(endpoint_name)
        except ResourceNotFoundError:
            endpoint = self._client.batch_endpoints.begin_create_or_update(
                BatchEndpoint(name=endpoint_name, description="Exact-quantity batch inference")
            ).result()
        expected_default = getattr(getattr(endpoint, "defaults", None), "deployment_name", None)
        deployment_name = _NAME.sub("-", f"v-{candidate.version}".lower()).strip("-")[:32]
        deployment = ModelBatchDeployment(
            name=deployment_name,
            endpoint_name=endpoint_name,
            model=candidate,
            code_configuration=CodeConfiguration(
                code=str(scoring_code),
                scoring_script="batch_driver.py",
            ),
            environment=environment_name,
            compute=compute_name,
            settings=ModelBatchDeploymentSettings(
                instance_count=1,
                max_concurrency_per_instance=2,
                mini_batch_size=10,
                output_action=BatchDeploymentOutputAction.APPEND_ROW,
                output_file_name="predictions.csv",
                retry_settings=BatchRetrySettings(max_retries=2, timeout=120),
                error_threshold=0,
                logging_level="info",
            ),
        )
        self._client.begin_create_or_update(deployment).result()
        endpoint = self._client.batch_endpoints.get(endpoint_name)
        current_default = getattr(getattr(endpoint, "defaults", None), "deployment_name", None)
        if current_default != expected_default:
            raise ConcurrentPromotionError(
                f"batch endpoint default changed from {expected_default!r} to {current_default!r}"
            )
        endpoint.defaults.deployment_name = deployment_name
        self._client.batch_endpoints.begin_create_or_update(endpoint).result()
        selected = ProductionDeployment(
            endpoint_name=endpoint_name,
            deployment_name=deployment_name,
            model_name=candidate.name,
            model_version=candidate.version,
            metrics=dict(candidate_metrics),
            mapping_version=candidate_mapping,
            mlflow_run_id=metadata["mlflow_run_id"],
        )
        return ModelSelection(candidate.name, candidate.version, decision, selected)

    def invoke_and_download(
        self,
        *,
        selected: ProductionDeployment,
        input_uri: str,
        output_dir: Path,
    ) -> Path:
        """Invoke one exact deployment and download its complete prediction artifact."""
        from azure.ai.ml import Input
        from azure.ai.ml.constants import AssetTypes

        job = self._client.batch_endpoints.invoke(
            endpoint_name=selected.endpoint_name,
            deployment_name=selected.deployment_name,
            input=Input(path=input_uri, type=AssetTypes.URI_FOLDER),
        )
        self._client.jobs.stream(job.name)
        terminal = self._client.jobs.get(job.name)
        if str(terminal.status).casefold() != "completed":
            raise RuntimeError(f"batch endpoint job {job.name} ended as {terminal.status}")
        download_dir = output_dir / "download"
        self._client.jobs.download(name=job.name, download_path=str(download_dir))
        matches = sorted(download_dir.rglob("predictions.csv"))
        if len(matches) != 1:
            raise RuntimeError(f"expected one predictions.csv from batch job, found {len(matches)}")
        output_dir.mkdir(parents=True, exist_ok=True)
        destination = output_dir / "predictions.csv"
        shutil.copy2(matches[0], destination)
        return destination

    def get_job_status(self, run_id: str) -> str:
        return str(self._client.jobs.get(run_id).status)

    def job_exists(self, name: str) -> bool:
        from azure.core.exceptions import ResourceNotFoundError

        try:
            self._client.jobs.get(name)
        except ResourceNotFoundError:
            return False
        return True

    def submit_retraining(
        self,
        *,
        name: str,
        source_event_id: str,
        source_batch_id: str,
        source_cutoff: str,
    ) -> None:
        if self._retraining_pipeline is None:
            raise RuntimeError("retraining pipeline path is not configured")
        from azure.ai.ml import load_job

        job = load_job(source=self._retraining_pipeline)
        job.name = name
        job.inputs["source_event_id"] = source_event_id
        job.inputs["source_batch_id"] = source_batch_id
        job.inputs["source_cutoff"] = source_cutoff
        self._client.jobs.create_or_update(job)
