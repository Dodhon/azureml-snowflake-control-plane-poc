from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from azureml_snowflake_poc.events import EventAction, EventContractError, process_event


@dataclass
class FakeJobGateway:
    authoritative_status: str
    existing_jobs: set[str] = field(default_factory=set)
    submissions: list[tuple[str, str, str, str]] = field(default_factory=list)

    def get_job_status(self, run_id: str) -> str:
        assert run_id
        return self.authoritative_status

    def job_exists(self, name: str) -> bool:
        return name in self.existing_jobs

    def submit_retraining(
        self,
        *,
        name: str,
        source_event_id: str,
        source_batch_id: str,
        source_cutoff: str,
    ) -> None:
        self.existing_jobs.add(name)
        self.submissions.append((name, source_event_id, source_batch_id, source_cutoff))


def monitor_event(event_id: str = "event-123") -> dict[str, object]:
    return {
        "id": event_id,
        "eventType": "Microsoft.MachineLearningServices.RunStatusChanged",
        "eventTime": "2026-07-14T12:00:00+00:00",
        "subject": "experiments/monitor/runs/run-42",
        "data": {
            "runId": "run-42",
            "runStatus": "Failed",
            "runTags": {
                "azureml_modelmonitor_threshold_breached": (
                    "has failed due to one or more features violating metric thresholds"
                )
            },
        },
    }


def test_threshold_event_submits_one_idempotent_retraining_job() -> None:
    # Contract: a confirmed monitor breach can submit one deterministic retraining job.
    # Edge: duplicate Event Grid deliveries are acknowledged without duplicate submission.
    gateway = FakeJobGateway(authoritative_status="Failed")

    first = process_event(
        monitor_event(),
        gateway,
        enable_auto_retrain=True,
        retraining_source_batch_id="monitor-batch-42",
    )
    second = process_event(
        monitor_event(),
        gateway,
        enable_auto_retrain=True,
        retraining_source_batch_id="monitor-batch-42",
    )

    assert first.action is EventAction.SUBMIT_RETRAIN
    assert second.action is EventAction.ALREADY_HANDLED
    assert len(gateway.submissions) == 1
    assert gateway.submissions[0][2:] == (
        "monitor-batch-42",
        "2026-07-14T12:00:00+00:00",
    )


def test_stale_or_nonterminal_event_rechecks_aml_source_of_truth() -> None:
    # Contract: Event Grid is a reaction bus; AML job state remains authoritative.
    # Edge: out-of-order failed events cannot retrain after the job is actually completed.
    gateway = FakeJobGateway(authoritative_status="Completed")

    result = process_event(monitor_event(), gateway, enable_auto_retrain=True)

    assert result.action is EventAction.IGNORE
    assert gateway.submissions == []


def test_auto_retraining_is_disabled_by_default() -> None:
    # Contract: monitoring stays active; automated retraining needs explicit enablement.
    # Edge: a real threshold breach is logged but does not create a pipeline loop by default.
    gateway = FakeJobGateway(authoritative_status="Failed")

    result = process_event(monitor_event(), gateway, enable_auto_retrain=False)

    assert result.action is EventAction.LOG_ONLY
    assert gateway.submissions == []


def test_enabled_retraining_requires_an_explicit_source_batch() -> None:
    gateway = FakeJobGateway(authoritative_status="Failed")

    with pytest.raises(EventContractError, match="RETRAIN_SOURCE_BATCH_ID"):
        process_event(monitor_event(), gateway, enable_auto_retrain=True)

    assert gateway.submissions == []
