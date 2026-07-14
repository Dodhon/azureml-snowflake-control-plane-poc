"""Azure Functions v2 Event Grid handler for Azure ML lifecycle events."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

import azure.functions as func

from azureml_snowflake_poc.aml_gateway import AzureMLGateway
from azureml_snowflake_poc.events import process_event

app = func.FunctionApp()


@app.function_name(name="aml_event_handler")
@app.event_grid_trigger(arg_name="event")
def aml_event_handler(event: func.EventGridEvent) -> None:
    payload = {
        "data": event.get_json(),
        "eventType": event.event_type,
        "id": event.id,
        "eventTime": event.event_time.isoformat(),
        "subject": event.subject,
    }
    pipeline_path = Path(
        os.environ.get("RETRAINING_PIPELINE_PATH", "azureml/pipelines/lifecycle.pipeline.yml")
    )
    gateway = AzureMLGateway.from_environment(retraining_pipeline=pipeline_path)
    auto_retrain = os.environ.get("RETRAIN_ON_MONITOR_BREACH", "false").casefold() == "true"
    result = process_event(
        payload,
        gateway,
        enable_auto_retrain=auto_retrain,
        retraining_source_batch_id=os.environ.get("RETRAIN_SOURCE_BATCH_ID"),
    )
    logging.info(
        json.dumps(
            {
                "action": result.action.value,
                "event_id": result.event_id,
                "event_type": event.event_type,
                "reason": result.reason,
                "retraining_job_name": result.retraining_job,
            },
            sort_keys=True,
        )
    )
