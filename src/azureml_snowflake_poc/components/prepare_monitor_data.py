"""Create MLTable-ready model input, output, reference, and ground-truth datasets."""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from azureml_snowflake_poc.component_io import (
    read_json,
    read_parquet_folder,
    write_json,
    write_parquet,
)
from azureml_snowflake_poc.configuration import load_configuration, require
from azureml_snowflake_poc.contracts import QuantityClassContract, label_actuals

_MLTABLE = """$schema: https://azuremlschemas.azureedge.net/latest/MLTable.schema.json
type: mltable
paths:
  - file: ./data.parquet
transformations:
  - read_parquet:
      include_path_column: false
"""


def _write_mltable(frame: pd.DataFrame, output_dir: Path) -> None:
    write_parquet(frame, output_dir, "data.parquet")
    (output_dir / "MLTable").write_text(_MLTABLE, encoding="utf-8")


def require_unique_correlation_ids(frame: pd.DataFrame, *, column: str, population: str) -> None:
    values = frame[column]
    if (
        values.isna().any()
        or values.astype("string").str.strip().eq("").any()
        or values.duplicated().any()
    ):
        raise ValueError(f"{population} require unique non-empty correlation IDs")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--features-input", type=Path, required=True)
    parser.add_argument("--training-input", type=Path, required=True)
    parser.add_argument("--actuals-input", type=Path, required=True)
    parser.add_argument("--predictions-input", type=Path, required=True)
    parser.add_argument("--publish-result", type=Path, required=True)
    parser.add_argument("--model-inputs-output", type=Path, required=True)
    parser.add_argument("--model-outputs-output", type=Path, required=True)
    parser.add_argument("--reference-output", type=Path, required=True)
    parser.add_argument("--ground-truth-output", type=Path, required=True)
    parser.add_argument("--manifest-output", type=Path, required=True)
    args = parser.parse_args()

    publish_result = read_json(args.publish_result)
    outputs = [
        args.model_inputs_output,
        args.model_outputs_output,
        args.reference_output,
        args.ground_truth_output,
    ]
    if publish_result.get("status") != "PUBLISHED":
        for output in outputs:
            output.mkdir(parents=True, exist_ok=True)
        write_json(args.manifest_output, {"status": "SKIPPED", "reason": "no published batch"})
        return 0

    config = load_configuration(args.config)
    entity_column = require(config, "data_contract.entity_column")
    feature_ts = require(config, "data_contract.feature_timestamp_column")
    event_ts = require(config, "data_contract.label_timestamp_column")
    correlation_column = require(config, "data_contract.correlation_column")
    feature_columns = require(config, "data_contract.feature_columns", list)
    features = read_parquet_folder(args.features_input)
    training = read_parquet_folder(args.training_input)
    actuals = read_parquet_folder(args.actuals_input)
    prediction_files = sorted(args.predictions_input.rglob("predictions.csv"))
    if len(prediction_files) != 1:
        raise RuntimeError(f"expected one predictions.csv, found {len(prediction_files)}")
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
    contract = QuantityClassContract(
        mapping_version=require(config, "quantity_contract.mapping_version"),
        minimum=require(config, "quantity_contract.minimum", int),
        maximum=require(config, "quantity_contract.maximum", int),
    )
    labeled_actuals = label_actuals(
        actuals,
        contract,
        quantity_column=require(config, "data_contract.actual_quantity_column"),
    )

    model_inputs = features.loc[
        :, [entity_column, feature_ts, correlation_column, *feature_columns]
    ].copy()
    model_outputs = predictions.loc[
        :, ["entity_id", "prediction_ts", "correlation_id", "prediction_class"]
    ].copy()
    reference = training.loc[
        :, [entity_column, feature_ts, *feature_columns, "quantity_class"]
    ].copy()
    reference["prediction_class"] = reference["quantity_class"]
    ground_truth = labeled_actuals.loc[
        :, [entity_column, event_ts, correlation_column, "quantity_class"]
    ].copy()
    ground_truth = ground_truth.rename(
        columns={
            correlation_column: "correlation_id",
            "quantity_class": "actual_class",
        }
    )
    require_unique_correlation_ids(
        model_outputs, column="correlation_id", population="model outputs"
    )
    require_unique_correlation_ids(ground_truth, column="correlation_id", population="ground truth")

    _write_mltable(model_inputs, args.model_inputs_output)
    _write_mltable(model_outputs, args.model_outputs_output)
    _write_mltable(reference, args.reference_output)
    _write_mltable(ground_truth, args.ground_truth_output)
    write_json(
        args.manifest_output,
        {
            "ground_truth_rows": len(ground_truth),
            "model_input_rows": len(model_inputs),
            "model_output_rows": len(model_outputs),
            "reference_rows": len(reference),
            "status": "READY",
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
