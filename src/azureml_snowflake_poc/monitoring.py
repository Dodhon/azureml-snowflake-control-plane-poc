"""Dependency-light Azure ML model-monitor schedule rendering."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

MONITOR_ASSETS = {
    "monitor_model_inputs": "exact-quantity-model-inputs",
    "monitor_model_outputs": "exact-quantity-model-outputs",
    "monitor_reference_data": "exact-quantity-reference",
    "monitor_ground_truth": "exact-quantity-ground-truth",
}

_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,254}")
_EMAIL = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.IGNORECASE)
_PLACEHOLDER = re.compile(r"\bCHANGE_ME_[A-Z0-9_]+\b")


def _name(value: str, label: str) -> str:
    if not _NAME.fullmatch(value):
        raise ValueError(f"{label} is not a valid Azure ML name")
    return value


def _integer(settings: Mapping[str, Any], key: str, minimum: int, maximum: int) -> int:
    value = settings.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise ValueError(f"monitoring.{key} must be an integer in [{minimum}, {maximum}]")
    return value


def _probability(settings: Mapping[str, Any], key: str) -> float:
    value = settings.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 1:
        raise ValueError(f"monitoring.{key} must be numeric in [0, 1]")
    return float(value)


def render_schedule(
    template: str,
    *,
    endpoint_name: str,
    deployment_name: str,
    version: str,
    email: str,
    monitoring: Mapping[str, Any],
) -> str:
    """Render one monitor schedule without permitting YAML-shaped substitutions."""
    frequency = monitoring.get("frequency")
    if frequency not in {"day", "hour", "minute", "month", "week"}:
        raise ValueError("monitoring.frequency must be an AML recurrence frequency")
    if not _EMAIL.fullmatch(email):
        raise ValueError("email must be one plain email address")

    replacements = {
        "CHANGE_ME_ENDPOINT": _name(endpoint_name, "endpoint_name"),
        "CHANGE_ME_DEPLOYMENT": _name(deployment_name, "deployment_name"),
        "CHANGE_ME_MODEL_INPUTS_ASSET": MONITOR_ASSETS["monitor_model_inputs"],
        "CHANGE_ME_MODEL_OUTPUTS_ASSET": MONITOR_ASSETS["monitor_model_outputs"],
        "CHANGE_ME_REFERENCE_ASSET": MONITOR_ASSETS["monitor_reference_data"],
        "CHANGE_ME_GROUND_TRUTH_ASSET": MONITOR_ASSETS["monitor_ground_truth"],
        "CHANGE_ME_ASSET_VERSION": _name(version, "version"),
        "CHANGE_ME_OPERATOR_EMAIL": email,
        "CHANGE_ME_MONITOR_FREQUENCY": frequency,
        "CHANGE_ME_MONITOR_INTERVAL": str(_integer(monitoring, "interval", 1, 1_000)),
        "CHANGE_ME_MONITOR_HOURS": str(_integer(monitoring, "hours", 0, 23)),
        "CHANGE_ME_MONITOR_MINUTES": str(_integer(monitoring, "minutes", 0, 59)),
        "CHANGE_ME_DATA_DRIFT_THRESHOLD": str(_probability(monitoring, "data_drift_threshold")),
        "CHANGE_ME_PREDICTION_DRIFT_P_VALUE": str(
            _probability(monitoring, "prediction_drift_p_value")
        ),
        "CHANGE_ME_PERFORMANCE_THRESHOLD": str(_probability(monitoring, "performance_threshold")),
    }
    for placeholder, value in replacements.items():
        template = template.replace(placeholder, value)
    unresolved = sorted(set(_PLACEHOLDER.findall(template)))
    if unresolved:
        raise ValueError(f"unresolved monitor placeholders: {', '.join(unresolved)}")
    return template
