from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]


def _driver() -> ModuleType:
    path = ROOT / "azureml/scoring/batch_driver.py"
    spec = importlib.util.spec_from_file_location("poc_batch_driver", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load batch driver")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _Model:
    def predict(self, frame: pd.DataFrame) -> pd.Series:
        assert list(frame.columns) == ["signal_a", "signal_b"]
        return pd.Series(["2"] * len(frame))


def test_batch_output_preserves_business_correlation_identity(tmp_path: Path) -> None:
    driver = _driver()
    driver._MODEL = _Model()
    driver._FEATURE_COLUMNS = ["signal_a", "signal_b"]
    driver._ENTITY_COLUMN = "entity_id"
    driver._TIMESTAMP_COLUMN = "feature_ts"
    driver._CORRELATION_COLUMN = "correlation_id"
    input_path = tmp_path / "batch.parquet"
    pd.DataFrame(
        {
            "entity_id": ["entity-1"],
            "feature_ts": ["2026-07-14T12:00:00Z"],
            "source_batch_id": ["batch-1"],
            "correlation_id": ["business-event-9"],
            "signal_a": [1.0],
            "signal_b": [2.0],
        }
    ).to_parquet(input_path)

    result = driver.run([str(input_path)])

    assert list(result.columns) == [
        "entity_id",
        "prediction_ts",
        "source_batch_id",
        "correlation_id",
        "prediction_class",
    ]
    assert result.loc[0, "correlation_id"] == "business-event-9"


def test_batch_scoring_rejects_missing_configured_feature(tmp_path: Path) -> None:
    driver = _driver()
    driver._MODEL = _Model()
    driver._FEATURE_COLUMNS = ["signal_a", "signal_b"]
    driver._ENTITY_COLUMN = "entity_id"
    driver._TIMESTAMP_COLUMN = "feature_ts"
    driver._CORRELATION_COLUMN = "correlation_id"
    input_path = tmp_path / "batch.parquet"
    pd.DataFrame(
        {
            "entity_id": ["entity-1"],
            "feature_ts": ["2026-07-14T12:00:00Z"],
            "source_batch_id": ["batch-1"],
            "correlation_id": ["business-event-9"],
            "signal_a": [1.0],
        }
    ).to_parquet(input_path)

    with pytest.raises(ValueError, match="missing columns: signal_b"):
        driver.run([str(input_path)])
