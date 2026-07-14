"""Explicit candidate-versus-production promotion policy."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from math import isfinite


class PromotionOutcome(StrEnum):
    PROMOTE = "PROMOTE"
    RETAIN = "RETAIN"
    HALT = "HALT"


@dataclass(frozen=True, slots=True)
class MetricRule:
    """One required absolute and optional champion-comparison metric rule."""

    name: str
    direction: str
    threshold: float
    minimum_delta: float = 0.0

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("metric rule name must not be empty")
        if self.direction not in {"maximize", "minimize"}:
            raise ValueError("direction must be 'maximize' or 'minimize'")
        if not isfinite(self.threshold):
            raise ValueError("threshold must be finite")
        if not isfinite(self.minimum_delta) or self.minimum_delta < 0:
            raise ValueError("minimum_delta must be finite and non-negative")


@dataclass(frozen=True, slots=True)
class GateDecision:
    """Durable model-policy result; reasons are empty only for promotion."""

    outcome: PromotionOutcome
    reasons: tuple[str, ...]
    candidate_metrics: Mapping[str, float]
    champion_metrics: Mapping[str, float] | None

    def to_dict(self) -> dict[str, object]:
        return {
            "outcome": self.outcome.value,
            "reasons": list(self.reasons),
            "candidate_metrics": dict(sorted(self.candidate_metrics.items())),
            "champion_metrics": (
                dict(sorted(self.champion_metrics.items()))
                if self.champion_metrics is not None
                else None
            ),
        }


def _finite_metric(
    metrics: Mapping[str, float], name: str, owner: str
) -> tuple[float | None, str | None]:
    value = metrics.get(name)
    if value is None:
        return None, f"missing {owner} metric: {name}"
    if not isfinite(float(value)):
        return None, f"nonfinite {owner} metric: {name}"
    return float(value), None


def evaluate_promotion(
    candidate_metrics: Mapping[str, float],
    champion_metrics: Mapping[str, float] | None,
    rules: tuple[MetricRule, ...],
    *,
    has_production_deployment: bool,
) -> GateDecision:
    """Apply complete-evidence, absolute-threshold, and comparison gates."""
    if not rules:
        raise ValueError("at least one promotion rule is required")

    reasons: list[str] = []
    for rule in rules:
        candidate, candidate_error = _finite_metric(candidate_metrics, rule.name, "candidate")
        if candidate_error:
            reasons.append(candidate_error)
            continue
        assert candidate is not None

        absolute_pass = (
            candidate >= rule.threshold
            if rule.direction == "maximize"
            else candidate <= rule.threshold
        )
        if not absolute_pass:
            comparator = ">=" if rule.direction == "maximize" else "<="
            reasons.append(
                f"candidate metric {rule.name}={candidate:.6g} does not satisfy "
                f"{comparator} {rule.threshold:.6g}"
            )

        if champion_metrics is None:
            continue

        champion, champion_error = _finite_metric(champion_metrics, rule.name, "champion")
        if champion_error:
            reasons.append(champion_error)
            continue
        assert champion is not None
        improvement = candidate - champion if rule.direction == "maximize" else champion - candidate
        if improvement < rule.minimum_delta:
            reasons.append(
                f"candidate metric {rule.name} improvement={improvement:.6g} is below "
                f"minimum_delta={rule.minimum_delta:.6g}"
            )

    if not reasons:
        outcome = PromotionOutcome.PROMOTE
    elif has_production_deployment:
        outcome = PromotionOutcome.RETAIN
    else:
        outcome = PromotionOutcome.HALT
        reasons.append("no production deployment is available")

    return GateDecision(
        outcome=outcome,
        reasons=tuple(reasons),
        candidate_metrics=dict(candidate_metrics),
        champion_metrics=dict(champion_metrics) if champion_metrics is not None else None,
    )
