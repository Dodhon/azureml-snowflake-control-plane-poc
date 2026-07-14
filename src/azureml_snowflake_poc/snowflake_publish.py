"""Transactional Snowflake publication for complete AML batch predictions."""

from __future__ import annotations

import re
from collections.abc import Iterable
from contextlib import suppress
from typing import Any

import pandas as pd

_IDENTIFIER_PART = re.compile(r"^[A-Z_][A-Z0-9_$]*$", re.IGNORECASE)
PREDICTION_COLUMNS = (
    "PREDICTION_ID",
    "SOURCE_BATCH_ID",
    "ENTITY_ID",
    "CORRELATION_ID",
    "PREDICTION_TS",
    "AML_PIPELINE_JOB_ID",
    "MLFLOW_RUN_ID",
    "FEATURE_SET_NAME",
    "FEATURE_SET_VERSION",
    "MODEL_NAME",
    "MODEL_VERSION",
    "BATCH_ENDPOINT_NAME",
    "BATCH_DEPLOYMENT_NAME",
    "QUANTITY_CLASS_MAPPING_VERSION",
    "PREDICTION_CLASS",
    "ACTUAL_QUANTITY",
    "ACTUAL_CLASS",
    "CREATED_AT",
    "UPDATED_AT",
)


def _validate_identifier(identifier: str) -> tuple[str, ...]:
    parts = tuple(identifier.split("."))
    if not 1 <= len(parts) <= 3 or any(not _IDENTIFIER_PART.fullmatch(part) for part in parts):
        raise ValueError(f"invalid Snowflake identifier: {identifier!r}")
    return tuple(part.upper() for part in parts)


def _merge_sql(target_table: str, staging_table: str) -> str:
    target = ".".join(_validate_identifier(target_table))
    staging = ".".join(_validate_identifier(staging_table))
    update_columns = tuple(column for column in PREDICTION_COLUMNS if column != "PREDICTION_ID")
    updates = ",\n        ".join(f"target.{column} = source.{column}" for column in update_columns)
    insert_columns = ", ".join(PREDICTION_COLUMNS)
    insert_values = ", ".join(f"source.{column}" for column in PREDICTION_COLUMNS)
    return f"""MERGE INTO {target} AS target
USING {staging} AS source
ON target.PREDICTION_ID = source.PREDICTION_ID
WHEN MATCHED THEN UPDATE SET
        {updates}
WHEN NOT MATCHED THEN INSERT ({insert_columns})
VALUES ({insert_values})"""


def build_merge_statements(*, target_table: str, staging_table: str) -> tuple[str, ...]:
    """Build the reviewable transaction used after staging is fully loaded."""
    return ("BEGIN", _merge_sql(target_table, staging_table), "COMMIT")


def validate_prediction_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """Return a column-ordered frame or fail before opening a transaction."""
    normalized = frame.rename(columns={column: str(column).upper() for column in frame.columns})
    missing = [column for column in PREDICTION_COLUMNS if column not in normalized.columns]
    if missing:
        raise ValueError(f"prediction frame is missing columns: {', '.join(missing)}")
    if normalized["PREDICTION_ID"].isna().any() or normalized["PREDICTION_ID"].duplicated().any():
        raise ValueError("PREDICTION_ID values must be non-null and unique within a batch")
    return normalized.loc[:, PREDICTION_COLUMNS]


def publish_predictions(
    connection: Any,
    frame: pd.DataFrame,
    *,
    target_table: str,
    staging_table: str,
) -> int:
    """Stage a complete frame, then atomically merge it into Snowflake."""
    from snowflake.connector.pandas_tools import write_pandas

    ordered = validate_prediction_frame(frame)
    target_parts = _validate_identifier(target_table)
    staging_parts = _validate_identifier(staging_table)
    if len(target_parts) != 3 or len(staging_parts) != 3:
        raise ValueError("target_table and staging_table must be fully qualified")
    if target_parts[:2] != staging_parts[:2]:
        raise ValueError("target and staging tables must share database and schema")

    database, schema, target_name = target_parts
    _, _, staging_name = staging_parts
    cursor = connection.cursor()
    try:
        create_stage = (
            f"CREATE OR REPLACE TEMPORARY TABLE {'.'.join(staging_parts)} "
            f"LIKE {'.'.join(target_parts)}"
        )
        cursor.execute(create_stage)
        success, _, loaded_rows, _ = write_pandas(
            connection,
            ordered,
            staging_name,
            database=database,
            schema=schema,
            quote_identifiers=False,
        )
        if not success or loaded_rows != len(ordered):
            raise RuntimeError(
                f"Snowflake staging load incomplete: expected {len(ordered)}, loaded {loaded_rows}"
            )

        for statement in build_merge_statements(
            target_table=".".join((*target_parts[:2], target_name)),
            staging_table=".".join(staging_parts),
        ):
            cursor.execute(statement)
        return loaded_rows
    except Exception:
        with suppress(Exception):
            cursor.execute("ROLLBACK")
        raise
    finally:
        cursor.close()


def render_sql(statements: Iterable[str]) -> str:
    """Render transaction statements for review or dry-run output."""
    return ";\n\n".join(statement.rstrip(";") for statement in statements) + ";\n"
