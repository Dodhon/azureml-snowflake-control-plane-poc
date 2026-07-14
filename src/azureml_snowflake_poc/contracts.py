"""Cross-platform data and exact-quantity class contracts."""

from __future__ import annotations

from dataclasses import dataclass
from numbers import Real

import pandas as pd


class ContractViolation(ValueError):
    """A hard data, version, or integration contract was violated."""


@dataclass(frozen=True, slots=True)
class QuantityClassContract:
    """Versioned mapping from exact integer quantities to canonical string classes."""

    mapping_version: str
    minimum: int
    maximum: int

    def __post_init__(self) -> None:
        if not self.mapping_version.strip():
            raise ValueError("mapping_version must not be empty")
        if self.minimum < 0:
            raise ValueError("minimum must be non-negative")
        if self.maximum < self.minimum:
            raise ValueError("maximum must be greater than or equal to minimum")

    def encode(self, value: object) -> str:
        """Validate and encode one exact quantity as a canonical decimal string."""
        if isinstance(value, bool) or not isinstance(value, Real):
            raise ContractViolation(f"quantity must be a real number, got {type(value).__name__}")

        numeric = float(value)
        if not pd.notna(numeric) or numeric in (float("inf"), float("-inf")):
            raise ContractViolation("quantity must be finite")
        if not numeric.is_integer():
            raise ContractViolation(f"quantity must be integral, got {value!r}")

        quantity = int(numeric)
        if not self.minimum <= quantity <= self.maximum:
            raise ContractViolation(
                f"quantity {quantity} is outside configured domain [{self.minimum}, {self.maximum}]"
            )
        return str(quantity)

    def require_mapping_version(self, observed: str | None, *, artifact: str) -> None:
        """Fail closed when an artifact speaks a different class-domain version."""
        if observed != self.mapping_version:
            raise ContractViolation(
                f"mapping version mismatch for {artifact}: expected {self.mapping_version!r}, "
                f"observed {observed!r}"
            )


_SCORING_LABEL_COLUMNS = {
    "actual_class",
    "actual_quantity",
    "quantity_class",
    "quantity_value",
    "target",
}


def validate_scoring_population(frame: pd.DataFrame) -> None:
    """Reject label leakage in current scoring features."""
    normalized = {str(column).lower() for column in frame.columns}
    leaked = sorted(normalized & _SCORING_LABEL_COLUMNS)
    if leaked:
        raise ContractViolation(f"scoring population contains label column(s): {', '.join(leaked)}")


def label_actuals(
    actuals: pd.DataFrame,
    contract: QuantityClassContract,
    *,
    quantity_column: str = "actual_quantity",
) -> pd.DataFrame:
    """Validate delayed/historical actuals and attach canonical class evidence."""
    if quantity_column not in actuals.columns:
        raise ContractViolation(f"actuals are missing required column {quantity_column!r}")

    labeled = actuals.copy()
    labeled["quantity_class"] = [contract.encode(value) for value in labeled[quantity_column]]
    labeled["quantity_class_mapping_version"] = contract.mapping_version
    return labeled
