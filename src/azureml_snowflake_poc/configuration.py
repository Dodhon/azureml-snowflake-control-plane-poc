"""Validated public configuration loading without secret values."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml


class ConfigurationError(ValueError):
    """Configuration is missing a required public, non-secret value."""


def load_configuration(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ConfigurationError("configuration root must be an object")
    return payload


def require(config: Mapping[str, Any], dotted_path: str, expected_type: type[Any] = str) -> Any:
    value: Any = config
    for part in dotted_path.split("."):
        if not isinstance(value, Mapping) or part not in value:
            raise ConfigurationError(f"missing configuration value: {dotted_path}")
        value = value[part]
    if not isinstance(value, expected_type):
        raise ConfigurationError(
            f"configuration value {dotted_path} must be {expected_type.__name__}"
        )
    if isinstance(value, str) and (not value.strip() or value.startswith("CHANGE_ME_")):
        raise ConfigurationError(f"configuration value is not replaced: {dotted_path}")
    return value
