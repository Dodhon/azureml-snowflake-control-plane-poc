"""Validate the complete batch and publish exact model-version predictions to Snowflake."""

from __future__ import annotations

import argparse
import hashlib
import os
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from azureml_snowflake_poc.component_io import read_json, read_parquet_folder, write_json
from azureml_snowflake_poc.configuration import load_configuration, require
from azureml_snowflake_poc.identity import prediction_id
from azureml_snowflake_poc.snowflake_io import connect
from azureml_snowflake_poc.snowflake_publish import publish_predictions


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--features-input", type=Path, required=True)
    parser.add_argument("--predictions-input", type=Path, required=True)
    parser.add_argument("--scoring-result", type=Path, required=True)
    parser.add_argument("--selection", type=Path, required=True)
    parser.add_argument("--publish-result", type=Path, required=True)
    args = parser.parse_args()

    scoring_result = read_json(args.scoring_result)
    if scoring_result.get("status") != "SCORED":
        write_json(
            args.publish_result,
            {"status": "SKIPPED", "reason": "batch scoring did not produce predictions"},
        )
        return 0

    config = load_configuration(args.config)
    features = read_parquet_folder(args.features_input)
    prediction_files = sorted(args.predictions_input.rglob("predictions.csv"))
    if len(prediction_files) != 1:
        raise RuntimeError(f"expected one prediction artifact, found {len(prediction_files)}")
    predictions = pd.read_csv(
        prediction_files[0],
        header=None,
        names=[
            "entity_id",
            "prediction_ts",
            "source_batch_id",
            "correlation_id",
            "prediction_class",
        ],
    )
    required_prediction_columns = {
        "entity_id",
        "prediction_ts",
        "source_batch_id",
        "correlation_id",
        "prediction_class",
    }
    missing = sorted(required_prediction_columns - set(predictions.columns))
    if missing:
        raise ValueError(f"batch predictions are missing columns: {', '.join(missing)}")
    entity_column = require(config, "data_contract.entity_column")
    timestamp_column = require(config, "data_contract.feature_timestamp_column")
    correlation_column = require(config, "data_contract.correlation_column")
    expected_keys = features.loc[:, [entity_column, timestamp_column, correlation_column]].copy()
    expected_keys.columns = ["entity_id", "prediction_ts", "correlation_id"]
    expected_keys["entity_id"] = expected_keys["entity_id"].astype(str)
    expected_keys["prediction_ts"] = pd.to_datetime(expected_keys["prediction_ts"], utc=True)
    expected_keys["correlation_id"] = expected_keys["correlation_id"].astype(str)
    actual_keys = predictions.loc[:, ["entity_id", "prediction_ts", "correlation_id"]].copy()
    actual_keys["entity_id"] = actual_keys["entity_id"].astype(str)
    actual_keys["prediction_ts"] = pd.to_datetime(actual_keys["prediction_ts"], utc=True)
    actual_keys["correlation_id"] = actual_keys["correlation_id"].astype(str)
    if actual_keys.duplicated().any():
        raise ValueError("batch predictions contain duplicate correlation keys")
    reconciled = expected_keys.merge(actual_keys, how="outer", indicator=True)
    if not reconciled["_merge"].eq("both").all():
        counts = reconciled["_merge"].value_counts().to_dict()
        raise ValueError(f"batch prediction reconciliation failed: {counts}")

    selection = read_json(args.selection)
    selected = selection["selected"]
    now = datetime.now(UTC).isoformat()
    pipeline_job_id = os.environ.get(
        "AZUREML_ROOT_RUN_ID", os.environ.get("AZUREML_RUN_ID", "local")
    )
    mlflow_run_id = str(selected["mlflow_run_id"])
    endpoint_name = str(selected["endpoint_name"])
    deployment_name = str(selected["deployment_name"])
    model_name = str(selected["model_name"])
    model_version = str(selected["model_version"])
    mapping_version = str(selected["mapping_version"])
    configured_mapping = require(config, "quantity_contract.mapping_version")
    if mapping_version != configured_mapping:
        raise ValueError("selected model quantity mapping does not match the publication contract")
    frame = pd.DataFrame(
        {
            "SOURCE_BATCH_ID": predictions["source_batch_id"].astype(str),
            "ENTITY_ID": predictions["entity_id"].astype(str),
            "CORRELATION_ID": predictions["correlation_id"].astype(str),
            "PREDICTION_TS": pd.to_datetime(predictions["prediction_ts"], utc=True),
            "AML_PIPELINE_JOB_ID": pipeline_job_id,
            "MLFLOW_RUN_ID": mlflow_run_id,
            "FEATURE_SET_NAME": require(config, "azure.feature_set_name"),
            "FEATURE_SET_VERSION": require(config, "azure.feature_set_version"),
            "MODEL_NAME": model_name,
            "MODEL_VERSION": model_version,
            "BATCH_ENDPOINT_NAME": endpoint_name,
            "BATCH_DEPLOYMENT_NAME": deployment_name,
            "QUANTITY_CLASS_MAPPING_VERSION": mapping_version,
            "PREDICTION_CLASS": predictions["prediction_class"].astype(str),
            "ACTUAL_QUANTITY": None,
            "ACTUAL_CLASS": None,
            "CREATED_AT": now,
            "UPDATED_AT": now,
        }
    )
    frame["PREDICTION_ID"] = [
        prediction_id(
            source_batch_id=source_batch,
            entity_id=entity,
            correlation_id=correlation,
            prediction_ts=prediction_ts.isoformat(),
            model_name=model_name,
            model_version=model_version,
            mapping_version=mapping_version,
        )
        for source_batch, entity, correlation, prediction_ts in zip(
            frame["SOURCE_BATCH_ID"],
            frame["ENTITY_ID"],
            frame["CORRELATION_ID"],
            frame["PREDICTION_TS"],
            strict=True,
        )
    ]
    target_table = require(config, "snowflake.predictions_table")
    suffix = hashlib.sha256(pipeline_job_id.encode()).hexdigest()[:12].upper()
    target_parts = target_table.split(".")
    staging_table = ".".join((*target_parts[:-1], f"{target_parts[-1]}_STAGE_{suffix}"))
    connection = connect(config)
    try:
        published_rows = publish_predictions(
            connection,
            frame,
            target_table=target_table,
            staging_table=staging_table,
        )
    finally:
        connection.close()
    write_json(
        args.publish_result,
        {
            "model_name": model_name,
            "model_version": model_version,
            "published_rows": published_rows,
            "source_batch_ids": sorted(frame["SOURCE_BATCH_ID"].unique().tolist()),
            "status": "PUBLISHED",
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
