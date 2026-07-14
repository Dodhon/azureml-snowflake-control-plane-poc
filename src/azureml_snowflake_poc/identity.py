"""Deterministic cross-system identities for retries and provenance."""

from __future__ import annotations

import hashlib
import json


def _digest(payload: dict[str, str], *, length: int = 32) -> str:
    for name, value in payload.items():
        if not value:
            raise ValueError(f"identity field {name!r} must not be empty")
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(canonical).hexdigest()[:length]


def prediction_id(
    *,
    source_batch_id: str,
    entity_id: str,
    correlation_id: str,
    prediction_ts: str,
    model_name: str,
    model_version: str,
    mapping_version: str,
) -> str:
    """Return a stable ID for one exact prediction and provenance tuple."""
    return "pred_" + _digest(
        {
            "entity_id": entity_id,
            "correlation_id": correlation_id,
            "mapping_version": mapping_version,
            "model_name": model_name,
            "model_version": model_version,
            "prediction_ts": prediction_ts,
            "source_batch_id": source_batch_id,
        }
    )


def retraining_job_name(event_id: str) -> str:
    """Map an Event Grid delivery identity to one AML-safe retraining job name."""
    return "retrain-" + _digest({"event_grid_event_id": event_id}, length=24)
