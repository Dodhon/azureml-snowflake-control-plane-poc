from __future__ import annotations

from azureml_snowflake_poc.identity import prediction_id, retraining_job_name


def test_prediction_identity_is_stable_and_version_specific() -> None:
    # Contract: publication retries resolve to the same business/provenance identity.
    # Edge: changing the exact model version must produce a distinct prediction identity.
    args = {
        "source_batch_id": "batch-2026-01-01",
        "entity_id": "entity-7",
        "correlation_id": "order-42",
        "prediction_ts": "2026-01-02T00:00:00Z",
        "model_name": "quantity-model",
        "model_version": "4",
        "mapping_version": "quantity-v1",
    }

    first = prediction_id(**args)
    second = prediction_id(**args)
    changed_model = prediction_id(**{**args, "model_version": "5"})
    changed_business_event = prediction_id(**{**args, "correlation_id": "order-43"})

    assert first == second
    assert first != changed_model
    assert first != changed_business_event
    assert first.startswith("pred_")


def test_event_identity_deduplicates_retraining_jobs() -> None:
    # Contract: Event Grid at-least-once delivery cannot create duplicate retraining jobs.
    # Edge: the same event ID maps to one AML-safe job name on every delivery.
    assert retraining_job_name("831e1650-001e-001b-66ab-eeb76e069631") == retraining_job_name(
        "831e1650-001e-001b-66ab-eeb76e069631"
    )
