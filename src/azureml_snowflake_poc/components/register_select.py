"""Register the candidate and apply the production batch-endpoint gate."""

from __future__ import annotations

import argparse
from pathlib import Path

from azureml_snowflake_poc.aml_gateway import AzureMLGateway
from azureml_snowflake_poc.component_io import read_json, write_json
from azureml_snowflake_poc.configuration import load_configuration, require
from azureml_snowflake_poc.gate import MetricRule


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--model-input", type=Path, required=True)
    parser.add_argument("--training-result", type=Path, required=True)
    parser.add_argument("--selection-output", type=Path, required=True)
    args = parser.parse_args()

    result = read_json(args.training_result)
    if result.get("status") != "TRAINED":
        write_json(
            args.selection_output,
            {
                "status": "SKIPPED",
                "reason": "candidate training did not complete",
                "selected": None,
            },
        )
        return 0

    config = load_configuration(args.config)
    rules = tuple(
        MetricRule(
            name=str(item["name"]),
            direction=str(item["direction"]),
            threshold=float(item["threshold"]),
            minimum_delta=float(item.get("minimum_delta", 0.0)),
        )
        for item in require(config, "promotion.rules", list)
    )
    gateway = AzureMLGateway.from_config(config)
    selection = gateway.register_and_select(
        model_path=args.model_input / "model",
        model_name=require(config, "azure.model_name"),
        candidate_version=str(result["candidate_version"]),
        candidate_metrics={str(key): float(value) for key, value in result["metrics"].items()},
        metadata={
            "quantity_class_mapping_version": str(result["mapping_version"]),
            "mlflow_run_id": str(result["mlflow_run_id"]),
            "model_implementation": str(result["model_implementation"]),
            "source_batch_id": str(result["source_batch_id"]),
            "training_snapshot_sha256": str(result["training_snapshot_sha256"]),
        },
        rules=rules,
        endpoint_name=require(config, "azure.batch_endpoint_name"),
        compute_name=require(config, "azure.batch_compute_name"),
        environment_name=require(config, "azure.inference_environment"),
        scoring_code=Path(require(config, "azure.scoring_code_path")),
    )
    payload = selection.to_dict()
    payload["status"] = "SELECTED" if selection.selected else "HALTED"
    write_json(args.selection_output, payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
