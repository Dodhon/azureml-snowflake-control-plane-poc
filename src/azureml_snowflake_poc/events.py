"""Idempotent Azure Machine Learning Event Grid reactions."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from azureml_snowflake_poc.identity import retraining_job_name


class EventContractError(ValueError):
    """An Event Grid payload is missing a required AML contract field."""


class EventAction(StrEnum):
    IGNORE = "IGNORE"
    LOG_ONLY = "LOG_ONLY"
    LOG_FAILURE = "LOG_FAILURE"
    SUBMIT_RETRAIN = "SUBMIT_RETRAIN"
    ALREADY_HANDLED = "ALREADY_HANDLED"


@dataclass(frozen=True, slots=True)
class EventResult:
    action: EventAction
    event_id: str
    reason: str
    retraining_job: str | None = None

    def to_dict(self) -> dict[str, str | None]:
        return {
            "action": self.action.value,
            "event_id": self.event_id,
            "reason": self.reason,
            "retraining_job": self.retraining_job,
        }


class JobGateway(Protocol):
    """Narrow AML control-plane seam used by the Event Grid function."""

    def get_job_status(self, run_id: str) -> str: ...

    def job_exists(self, name: str) -> bool: ...

    def submit_retraining(
        self,
        *,
        name: str,
        source_event_id: str,
        source_batch_id: str,
        source_cutoff: str,
    ) -> None: ...


def _casefold_mapping(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping):
        return {}
    return {str(key).casefold(): item for key, item in value.items()}


def _required_string(mapping: Mapping[str, object], *names: str) -> str:
    folded = _casefold_mapping(mapping)
    for name in names:
        value = folded.get(name.casefold())
        if isinstance(value, str) and value:
            return value
    raise EventContractError(f"event is missing required field: {'/'.join(names)}")


def process_event(
    event: Mapping[str, object],
    gateway: JobGateway,
    *,
    enable_auto_retrain: bool,
    retraining_source_batch_id: str | None = None,
) -> EventResult:
    """React to one AML event after rechecking authoritative job state."""
    event_id = _required_string(event, "id")
    event_type = _required_string(event, "eventType", "type")
    data = event.get("data")
    if not isinstance(data, Mapping):
        raise EventContractError("event data must be an object")

    if event_type != "Microsoft.MachineLearningServices.RunStatusChanged":
        return EventResult(EventAction.LOG_ONLY, event_id, f"observed {event_type}")

    run_id = _required_string(data, "runId")
    event_status = _required_string(data, "runStatus")
    authoritative_status = gateway.get_job_status(run_id)
    if authoritative_status.casefold() != "failed":
        return EventResult(
            EventAction.IGNORE,
            event_id,
            f"authoritative AML status is {authoritative_status}, event carried {event_status}",
        )

    tags = _casefold_mapping(_casefold_mapping(data).get("runtags"))
    breach = tags.get("azureml_modelmonitor_threshold_breached")
    if not isinstance(breach, str) or not breach.strip():
        return EventResult(
            EventAction.LOG_FAILURE, event_id, "AML run failed without monitor breach"
        )

    if not enable_auto_retrain:
        return EventResult(
            EventAction.LOG_ONLY, event_id, "monitor breach observed; auto retrain disabled"
        )

    if not retraining_source_batch_id:
        raise EventContractError(
            "RETRAIN_SOURCE_BATCH_ID is required when automatic retraining is enabled"
        )
    source_cutoff = _required_string(event, "eventTime")
    job_name = retraining_job_name(event_id)
    if gateway.job_exists(job_name):
        return EventResult(
            EventAction.ALREADY_HANDLED,
            event_id,
            "deterministic retraining job already exists",
            retraining_job=job_name,
        )

    gateway.submit_retraining(
        name=job_name,
        source_event_id=event_id,
        source_batch_id=retraining_source_batch_id,
        source_cutoff=source_cutoff,
    )
    return EventResult(
        EventAction.SUBMIT_RETRAIN,
        event_id,
        "monitor breach confirmed against AML job state",
        retraining_job=job_name,
    )
