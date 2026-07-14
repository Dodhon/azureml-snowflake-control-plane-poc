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
from azure.identity import DefaultAzureCredential

from azureml_snowflake_poc.configuration import load_configuration, require
from azureml_snowflake_poc.monitoring import MONITOR_ASSETS, render_schedule


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
    args = parser.parse_args()
    config = load_configuration(args.config)
    monitoring = require(config, "monitoring", dict)

    ml_client = client()
    job = ml_client.jobs.get(args.job_name)
    if str(job.status).casefold() != "completed":
        raise RuntimeError(f"pipeline job must be Completed, got {job.status}")
    version = hashlib.sha256(args.job_name.encode()).hexdigest()[:12]
    for output_name, asset_name in MONITOR_ASSETS.items():
        output = job.outputs.get(output_name)
        path = getattr(output, "path", None)
        if not path:
            raise RuntimeError(f"pipeline output {output_name!r} has no durable AML path")
        ml_client.data.create_or_update(
            Data(name=asset_name, version=version, path=path, type=AssetTypes.MLTABLE)
        )

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
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
