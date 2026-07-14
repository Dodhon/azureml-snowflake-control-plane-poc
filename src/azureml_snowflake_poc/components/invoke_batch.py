"""Invoke the exact selected Azure ML batch deployment."""

from __future__ import annotations

import argparse
from pathlib import Path

from azureml_snowflake_poc.aml_gateway import AzureMLGateway, ProductionDeployment
from azureml_snowflake_poc.component_io import read_json, write_json
from azureml_snowflake_poc.configuration import load_configuration


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selection", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--features-input", type=Path, required=True)
    parser.add_argument("--predictions-output", type=Path, required=True)
    parser.add_argument("--result-output", type=Path, required=True)
    args = parser.parse_args()

    config = load_configuration(args.config)
    selection = read_json(args.selection)
    selected_payload = selection.get("selected")
    if not isinstance(selected_payload, dict):
        args.predictions_output.mkdir(parents=True, exist_ok=True)
        write_json(
            args.result_output,
            {"status": "SKIPPED", "reason": "no deployable model was selected"},
        )
        return 0
    selected = ProductionDeployment(
        endpoint_name=str(selected_payload["endpoint_name"]),
        deployment_name=str(selected_payload["deployment_name"]),
        model_name=str(selected_payload["model_name"]),
        model_version=str(selected_payload["model_version"]),
        metrics={str(key): float(value) for key, value in selected_payload["metrics"].items()},
        mapping_version=str(selected_payload["mapping_version"]),
        mlflow_run_id=str(selected_payload["mlflow_run_id"]),
    )
    gateway = AzureMLGateway.from_config(config)
    prediction_path = gateway.invoke_and_download(
        selected=selected,
        input_uri=str(args.features_input),
        output_dir=args.predictions_output,
    )
    write_json(
        args.result_output,
        {
            "deployment_name": selected.deployment_name,
            "model_name": selected.model_name,
            "model_version": selected.model_version,
            "prediction_artifact": prediction_path.name,
            "status": "SCORED",
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
