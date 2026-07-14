#!/usr/bin/env python3
"""Load committed Azure ML YAML through the pinned SDK without cloud credentials."""

from __future__ import annotations

import tempfile
from pathlib import Path

from azure.ai.ml import (
    load_component,
    load_environment,
    load_feature_set,
    load_feature_store_entity,
    load_job,
)
from azure.ai.ml.entities._load_functions import load_schedule

from azureml_snowflake_poc.configuration import load_configuration, require
from azureml_snowflake_poc.monitoring import render_schedule

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    loaded: list[str] = []
    for path in sorted((ROOT / "azureml/components").glob("*/component.yml")):
        load_component(source=path)
        loaded.append(str(path.relative_to(ROOT)))

    load_environment(source=ROOT / "azureml/environments/runtime.environment.yml")
    loaded.append("azureml/environments/runtime.environment.yml")
    load_job(source=ROOT / "azureml/pipelines/lifecycle.pipeline.yml")
    loaded.append("azureml/pipelines/lifecycle.pipeline.yml")
    load_feature_store_entity(source=ROOT / "feature_store/entities/entity.yaml")
    loaded.append("feature_store/entities/entity.yaml")
    load_feature_set(source=ROOT / "feature_store/featuresets/exact_quantity/featureset.yaml")
    loaded.append("feature_store/featuresets/exact_quantity/featureset.yaml")

    config = load_configuration(ROOT / "config/poc.yaml")
    monitoring = require(config, "monitoring", dict)
    schedule = render_schedule(
        (ROOT / "azureml/monitoring/model-monitor.schedule.yml").read_text(),
        endpoint_name="exact-quantity-batch",
        deployment_name="model-1",
        version="validation1",
        email="ml-ops@example.com",
        monitoring=monitoring,
    )
    with tempfile.TemporaryDirectory() as directory:
        rendered = Path(directory) / "model-monitor.schedule.yml"
        rendered.write_text(schedule, encoding="utf-8")
        load_schedule(source=rendered)
    loaded.append("azureml/monitoring/model-monitor.schedule.yml (rendered)")

    for asset in loaded:
        print(f"loaded: {asset}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
