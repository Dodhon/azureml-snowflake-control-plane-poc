"""Train and evaluate one deterministic MLflow model candidate."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import mlflow
import mlflow.sklearn
import pandas as pd

from azureml_snowflake_poc.component_io import read_json, read_parquet_folder, write_json
from azureml_snowflake_poc.configuration import load_configuration, require
from azureml_snowflake_poc.modeling import MODEL_IMPLEMENTATION_VERSION, train_classifier


def _snapshot_digest(
    frame: pd.DataFrame,
    *,
    entity_column: str,
    label_timestamp_column: str,
) -> str:
    ordered = frame.sort_values(
        [entity_column, label_timestamp_column],
        kind="stable",
    ).reset_index(drop=True)
    schema = [(str(column), str(dtype)) for column, dtype in ordered.dtypes.items()]
    row_hashes = pd.util.hash_pandas_object(ordered, index=False).values.tobytes()
    digest = hashlib.sha256()
    digest.update(json.dumps(schema, separators=(",", ":")).encode())
    digest.update(row_hashes)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--training-input", type=Path, required=True)
    parser.add_argument("--data-decision", type=Path, required=True)
    parser.add_argument("--source-manifest", type=Path, required=True)
    parser.add_argument("--model-output", type=Path, required=True)
    parser.add_argument("--result-output", type=Path, required=True)
    args = parser.parse_args()

    data_decision = read_json(args.data_decision)
    if data_decision.get("decision") != "PASS":
        args.model_output.mkdir(parents=True, exist_ok=True)
        write_json(
            args.result_output,
            {"status": "SKIPPED", "reason": "data contract blocked training"},
        )
        return 0

    config = load_configuration(args.config)
    training = read_parquet_folder(args.training_input)
    feature_columns = require(config, "data_contract.feature_columns", list)
    entity_column = require(config, "data_contract.entity_column")
    feature_timestamp_column = require(config, "data_contract.feature_timestamp_column")
    correlation_column = require(config, "data_contract.correlation_column")
    label_timestamp_column = require(config, "data_contract.label_timestamp_column")
    random_seed = require(config, "training.random_seed", int)
    source_manifest = read_json(args.source_manifest)
    result = train_classifier(
        training,
        feature_columns=feature_columns,
        random_seed=random_seed,
    )
    source_batch_id = str(source_manifest["source_batch_id"])
    mapping_version = str(data_decision["mapping_version"])
    snapshot_digest = _snapshot_digest(
        training,
        entity_column=entity_column,
        label_timestamp_column=label_timestamp_column,
    )
    version_material = {
        "actuals_query_sha256": source_manifest["actuals_query_sha256"],
        "feature_columns": feature_columns,
        "entity_column": entity_column,
        "feature_timestamp_column": feature_timestamp_column,
        "correlation_column": correlation_column,
        "mapping_version": mapping_version,
        "model_implementation": MODEL_IMPLEMENTATION_VERSION,
        "random_seed": random_seed,
        "snapshot_sha256": snapshot_digest,
        "source_cutoff": source_manifest["source_cutoff"],
        "training_features_query_sha256": source_manifest["training_features_query_sha256"],
    }
    candidate_version = hashlib.sha256(
        json.dumps(version_material, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()[:16]
    tags = {
        "candidate_version": candidate_version,
        "model_implementation": MODEL_IMPLEMENTATION_VERSION,
        "quantity_class_mapping_version": mapping_version,
        "source_batch_id": source_batch_id,
        "training_snapshot_sha256": snapshot_digest,
    }
    with mlflow.start_run(run_name=f"candidate-{candidate_version}") as active_run:
        mlflow_run_id = active_run.info.run_id
        mlflow.log_metrics(result.metrics)
        mlflow.set_tags(tags)
        mlflow.sklearn.save_model(
            result.model,
            path=str(args.model_output / "model"),
            input_example=training.loc[:, feature_columns].head(3),
            metadata={
                **tags,
                "correlation_column": correlation_column,
                "entity_column": entity_column,
                "feature_timestamp_column": feature_timestamp_column,
                "mlflow_run_id": mlflow_run_id,
            },
        )
    write_json(
        args.result_output,
        {
            "candidate_version": candidate_version,
            "mapping_version": mapping_version,
            "metrics": result.metrics,
            "mlflow_run_id": mlflow_run_id,
            "model_implementation": MODEL_IMPLEMENTATION_VERSION,
            "source_batch_id": source_batch_id,
            "status": "TRAINED",
            "training_snapshot_sha256": snapshot_digest,
            "validation_rows": result.validation_rows,
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
