#!/usr/bin/env python3
"""Register exact pipeline monitor outputs and render the AML monitor schedule."""

from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path

from azure.ai.ml import MLClient
from azure.ai.ml.constants import AssetTypes
from azure.ai.ml.entities import Data
from azure.ai.ml.entities._load_functions import load_schedule
from azure.identity import DefaultAzureCredential

from azureml_snowflake_poc.configuration import load_configuration, require
from azureml_snowflake_poc.monitoring import MONITOR_ASSETS, apply_schedule, render_schedule


def client() -> MLClient:
    names = ("AZURE_SUBSCRIPTION_ID", "AZURE_RESOURCE_GROUP", "AZUREML_WORKSPACE_NAME")
    values = {name: os.environ.get(name) for name in names}
    missing = [name for name, value in values.items() if not value]
    if missing:
        raise RuntimeError(f"missing Azure environment variables: {', '.join(missing)}")
    return MLClient(
        DefaultAzureCredential(),
        values["AZURE_SUBSCRIPTION_ID"],
        values["AZURE_RESOURCE_GROUP"],
        values["AZUREML_WORKSPACE_NAME"],
    )


def configure(
    args: argparse.Namespace,
    ml_client: MLClient | None,
    *,
    schedule_loader=load_schedule,
) -> str | None:
    """Render and validate one job-derived schedule, then optionally apply it."""
    config = load_configuration(args.config)
    monitoring = require(config, "monitoring", dict)
    version = hashlib.sha256(args.job_name.encode()).hexdigest()[:12]
    assets: list[tuple[str, str]] = []
    if not args.render_only:
        if ml_client is None:
            raise RuntimeError("Azure ML client is required when applying a monitor")
        job = ml_client.jobs.get(args.job_name)
        if str(job.status).casefold() != "completed":
            raise RuntimeError(f"pipeline job must be Completed, got {job.status}")
        for output_name, asset_name in MONITOR_ASSETS.items():
            output = job.outputs.get(output_name)
            path = getattr(output, "path", None)
            if not path:
                raise RuntimeError(f"pipeline output {output_name!r} has no durable AML path")
            assets.append((asset_name, path))

    rendered = render_schedule(
        args.template.read_text(encoding="utf-8"),
        endpoint_name=args.endpoint_name,
        deployment_name=args.deployment_name,
        version=version,
        email=args.email,
        monitoring=monitoring,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(rendered, encoding="utf-8")
    schedule = schedule_loader(source=args.output)
    print(args.output)
    if args.render_only:
        return None
    assert ml_client is not None

    for asset_name, path in assets:
        ml_client.data.create_or_update(
            Data(name=asset_name, version=version, path=path, type=AssetTypes.MLTABLE)
        )
    name = apply_schedule(ml_client, schedule)
    print(f"updated Azure ML schedule: {name}")
    return name


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job-name", required=True)
    parser.add_argument("--endpoint-name", required=True)
    parser.add_argument("--deployment-name", required=True)
    parser.add_argument("--email", required=True)
    parser.add_argument("--config", type=Path, default=Path("config/poc.yaml"))
    parser.add_argument(
        "--template",
        type=Path,
        default=Path("azureml/monitoring/model-monitor.schedule.yml"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(".validation/model-monitor.rendered.yml"),
    )
    parser.add_argument(
        "--render-only",
        action="store_true",
        help="Render and validate the schedule without updating Azure ML.",
    )
    args = parser.parse_args()
    configure(args, None if args.render_only else client())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
