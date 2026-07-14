"""Azure ML batch deployment scoring contract."""

from __future__ import annotations

import os
from pathlib import Path

import mlflow.pyfunc
import pandas as pd

_MODEL: mlflow.pyfunc.PyFuncModel | None = None
_FEATURE_COLUMNS: list[str] = []
_ENTITY_COLUMN = ""
_TIMESTAMP_COLUMN = ""
_CORRELATION_COLUMN = ""


def init() -> None:
    global _MODEL, _FEATURE_COLUMNS, _ENTITY_COLUMN, _TIMESTAMP_COLUMN, _CORRELATION_COLUMN
    model_root = Path(os.environ["AZUREML_MODEL_DIR"])
    candidates = [path.parent for path in model_root.rglob("MLmodel")]
    if len(candidates) != 1:
        raise RuntimeError(
            f"expected one MLflow model under AZUREML_MODEL_DIR, found {len(candidates)}"
        )
    _MODEL = mlflow.pyfunc.load_model(str(candidates[0]))
    signature = _MODEL.metadata.signature
    if signature is None or signature.inputs is None:
        raise RuntimeError("registered model is missing an input signature")
    _FEATURE_COLUMNS = list(signature.inputs.input_names())
    model_metadata = _MODEL.metadata.metadata or {}
    try:
        _ENTITY_COLUMN = str(model_metadata["entity_column"])
        _TIMESTAMP_COLUMN = str(model_metadata["feature_timestamp_column"])
        _CORRELATION_COLUMN = str(model_metadata["correlation_column"])
    except KeyError as error:
        raise RuntimeError(
            f"registered model is missing scoring metadata: {error.args[0]}"
        ) from error


def run(mini_batch: list[str]) -> pd.DataFrame:
    if _MODEL is None:
        raise RuntimeError("batch driver init() did not complete")
    frames = []
    for item in mini_batch:
        path = Path(item)
        frame = pd.read_parquet(path) if path.suffix.casefold() == ".parquet" else pd.read_csv(path)
        required = [
            _ENTITY_COLUMN,
            _TIMESTAMP_COLUMN,
            _CORRELATION_COLUMN,
            "source_batch_id",
            *_FEATURE_COLUMNS,
        ]
        missing = [column for column in required if column not in frame.columns]
        if missing:
            raise ValueError(f"batch input is missing columns: {', '.join(missing)}")
        predicted = _MODEL.predict(frame.loc[:, _FEATURE_COLUMNS]).astype(str)
        frames.append(
            pd.DataFrame(
                {
                    "entity_id": frame[_ENTITY_COLUMN].astype(str),
                    "prediction_ts": frame[_TIMESTAMP_COLUMN].astype(str),
                    "source_batch_id": frame["source_batch_id"].astype(str),
                    "correlation_id": frame[_CORRELATION_COLUMN].astype(str),
                    "prediction_class": predicted,
                }
            )
        )
    if not frames:
        return pd.DataFrame(
            columns=[
                "entity_id",
                "prediction_ts",
                "source_batch_id",
                "correlation_id",
                "prediction_class",
            ]
        )
    return pd.concat(frames, ignore_index=True)
