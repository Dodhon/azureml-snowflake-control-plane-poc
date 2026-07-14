"""Validate populations, build predictors, and create a point-in-time training spine."""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from azureml_snowflake_poc.component_io import read_parquet_folder, write_json, write_parquet
from azureml_snowflake_poc.configuration import load_configuration, require
from azureml_snowflake_poc.contracts import (
    ContractViolation,
    QuantityClassContract,
    label_actuals,
    validate_correlation_ids,
)
from azureml_snowflake_poc.features import build_feature_frame, build_training_spine


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--scoring-input", type=Path, required=True)
    parser.add_argument("--training-features-input", type=Path, required=True)
    parser.add_argument("--actuals-input", type=Path, required=True)
    parser.add_argument("--features-output", type=Path, required=True)
    parser.add_argument("--training-output", type=Path, required=True)
    parser.add_argument("--decision-output", type=Path, required=True)
    args = parser.parse_args()

    config = load_configuration(args.config)
    scoring = read_parquet_folder(args.scoring_input)
    raw_training_features = read_parquet_folder(args.training_features_input)
    actuals = read_parquet_folder(args.actuals_input)
    entity_column = require(config, "data_contract.entity_column")
    feature_ts = require(config, "data_contract.feature_timestamp_column")
    label_ts = require(config, "data_contract.label_timestamp_column")
    feature_columns = require(config, "data_contract.feature_columns", list)
    correlation_column = require(config, "data_contract.correlation_column")
    contract = QuantityClassContract(
        mapping_version=require(config, "quantity_contract.mapping_version"),
        minimum=require(config, "quantity_contract.minimum", int),
        maximum=require(config, "quantity_contract.maximum", int),
    )

    try:
        if scoring.empty:
            raise ContractViolation("Snowflake scoring pull returned no rows")
        if raw_training_features.empty:
            raise ContractViolation("Snowflake training-feature pull returned no rows")
        if actuals.empty:
            raise ContractViolation("Snowflake actuals pull returned no rows")
        validate_correlation_ids(scoring, correlation_column)
        features = build_feature_frame(
            scoring,
            entity_column=entity_column,
            timestamp_column=feature_ts,
            feature_columns=feature_columns,
            passthrough_columns=["source_batch_id", correlation_column],
        )
        training_features = build_feature_frame(
            raw_training_features,
            entity_column=entity_column,
            timestamp_column=feature_ts,
            feature_columns=feature_columns,
        )
        labeled = label_actuals(
            actuals,
            contract,
            quantity_column=require(config, "data_contract.actual_quantity_column"),
        )
        training = build_training_spine(
            training_features,
            labeled,
            entity_column=entity_column,
            feature_timestamp_column=feature_ts,
            label_timestamp_column=label_ts,
            tolerance=pd.Timedelta(require(config, "data_contract.point_in_time_tolerance")),
        )
    except ContractViolation as error:
        write_json(
            args.decision_output,
            {
                "decision": "BLOCK",
                "reason": str(error),
                "mapping_version": contract.mapping_version,
            },
        )
        write_parquet(pd.DataFrame(), args.features_output, "features.parquet")
        write_parquet(pd.DataFrame(), args.training_output, "training.parquet")
        return 0

    write_parquet(features, args.features_output, "features.parquet")
    write_parquet(training, args.training_output, "training.parquet")
    write_json(
        args.decision_output,
        {
            "decision": "PASS",
            "feature_rows": len(features),
            "mapping_version": contract.mapping_version,
            "training_rows": len(training),
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
