from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from azureml_snowflake_poc.components.prepare_monitor_data import (
    require_unique_correlation_ids,
)
from azureml_snowflake_poc.configuration import load_configuration, require
from azureml_snowflake_poc.monitoring import render_schedule

ROOT = Path(__file__).resolve().parents[1]


def test_monitor_schedule_renders_configured_recurrence_and_thresholds() -> None:
    template = (ROOT / "azureml/monitoring/model-monitor.schedule.yml").read_text()
    settings = require(load_configuration(ROOT / "config/poc.yaml"), "monitoring", dict)

    rendered = render_schedule(
        template,
        endpoint_name="exact-quantity-batch",
        deployment_name="model-42",
        version="deadbeef1234",
        email="ml-ops@example.com",
        monitoring=settings,
    )

    assert "CHANGE_ME_" not in rendered
    assert "frequency: day" in rendered
    assert "jensen_shannon_distance: 0.25" in rendered
    assert "pearsons_chi_squared_test: 0.05" in rendered
    assert "accuracy: 0.65" in rendered
    assert "correlation_id: correlation_id" in rendered


def test_monitor_schedule_rejects_yaml_shaped_operator_values() -> None:
    settings = require(load_configuration(ROOT / "config/poc.yaml"), "monitoring", dict)

    with pytest.raises(ValueError, match="valid Azure ML name"):
        render_schedule(
            "endpoint: CHANGE_ME_ENDPOINT",
            endpoint_name="safe\ninjected: true",
            deployment_name="model-42",
            version="1",
            email="ml-ops@example.com",
            monitoring=settings,
        )


@pytest.mark.parametrize("correlation_ids", [[None], [""], ["event-1", "event-1"]])
def test_monitor_join_requires_unique_non_empty_business_identity(
    correlation_ids: list[str | None],
) -> None:
    frame = pd.DataFrame({"correlation_id": correlation_ids})

    with pytest.raises(ValueError, match="unique non-empty correlation IDs"):
        require_unique_correlation_ids(frame, column="correlation_id", population="model outputs")
