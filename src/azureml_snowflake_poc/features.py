"""Feature snapshot and point-in-time training-spine operations."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence

import pandas as pd

from azureml_snowflake_poc.contracts import ContractViolation, validate_scoring_population


def _require_columns(frame: pd.DataFrame, required: Sequence[str], *, population: str) -> None:
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise ContractViolation(f"{population} is missing columns: {', '.join(missing)}")


def build_feature_frame(
    raw: pd.DataFrame,
    *,
    entity_column: str,
    timestamp_column: str,
    feature_columns: Sequence[str],
    passthrough_columns: Sequence[str] = (),
) -> pd.DataFrame:
    """Create a deterministic predictor-only feature snapshot."""
    required = [entity_column, timestamp_column, *feature_columns, *passthrough_columns]
    _require_columns(raw, required, population="source features")
    frame = raw.loc[:, required].copy()
    validate_scoring_population(frame)
    if frame[entity_column].isna().any() or frame[timestamp_column].isna().any():
        raise ContractViolation("feature entity and timestamp keys must be non-null")
    frame[timestamp_column] = pd.to_datetime(frame[timestamp_column], utc=True)
    if frame.duplicated([entity_column, timestamp_column]).any():
        raise ContractViolation("feature entity/timestamp grain must be unique")
    for column in feature_columns:
        if frame[column].isna().any():
            raise ContractViolation(f"feature column {column!r} contains nulls")
    row_payload = frame.astype(str).agg("\x1f".join, axis=1)
    frame["feature_row_hash"] = [
        hashlib.sha256(value.encode()).hexdigest() for value in row_payload
    ]
    return frame.sort_values([entity_column, timestamp_column], kind="stable").reset_index(
        drop=True
    )


def build_training_spine(
    features: pd.DataFrame,
    labeled_actuals: pd.DataFrame,
    *,
    entity_column: str,
    feature_timestamp_column: str,
    label_timestamp_column: str,
    tolerance: pd.Timedelta | None = None,
) -> pd.DataFrame:
    """Point-in-time join each label to the latest feature row not after label time."""
    _require_columns(
        features,
        [entity_column, feature_timestamp_column],
        population="feature snapshot",
    )
    _require_columns(
        labeled_actuals,
        [
            entity_column,
            label_timestamp_column,
            "quantity_class",
            "quantity_class_mapping_version",
        ],
        population="labeled actuals",
    )
    left = labeled_actuals.copy()
    right = features.copy()
    left[label_timestamp_column] = pd.to_datetime(left[label_timestamp_column], utc=True)
    right[feature_timestamp_column] = pd.to_datetime(right[feature_timestamp_column], utc=True)
    left = left.sort_values([label_timestamp_column, entity_column], kind="stable")
    right = right.sort_values([feature_timestamp_column, entity_column], kind="stable")
    spine = pd.merge_asof(
        left,
        right,
        left_on=label_timestamp_column,
        right_on=feature_timestamp_column,
        by=entity_column,
        direction="backward",
        tolerance=tolerance,
        allow_exact_matches=True,
    )
    if spine[feature_timestamp_column].isna().any():
        raise ContractViolation("one or more labels have no point-in-time feature row")
    return spine.reset_index(drop=True)
