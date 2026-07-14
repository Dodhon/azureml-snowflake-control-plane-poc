"""Credential-free acceptance demo for the five lifecycle outcomes."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

import pandas as pd
from sklearn.dummy import DummyClassifier
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import f1_score, log_loss

from azureml_snowflake_poc.contracts import (
    ContractViolation,
    QuantityClassContract,
    label_actuals,
    validate_scoring_population,
)
from azureml_snowflake_poc.gate import MetricRule, PromotionOutcome, evaluate_promotion
from azureml_snowflake_poc.identity import prediction_id


class Scenario(StrEnum):
    BEST_CASE = "best-case"
    INVALID_LABEL = "invalid-label"
    WEAK_CANDIDATE = "weak-candidate"
    DRIFT = "drift"
    TECHNICAL_FAILURE = "technical-failure"


@dataclass(frozen=True, slots=True)
class ScenarioResult:
    scenario: str
    terminal_state: str
    gate_outcome: str | None
    gate_reasons: tuple[str, ...]
    selected_model_version: str | None
    prediction_rows: tuple[dict[str, str], ...]
    monitor_alert: bool
    technical_error: str | None = None

    def to_json(self) -> str:
        return json.dumps(asdict(self), sort_keys=True, separators=(",", ":"))


_CONTRACT = QuantityClassContract(mapping_version="quantity-v1", minimum=0, maximum=2)
_RULES = (
    MetricRule("macro_f1", "maximize", threshold=0.75, minimum_delta=0.01),
    MetricRule("log_loss", "minimize", threshold=0.70, minimum_delta=0.01),
)


def _training_data() -> tuple[pd.DataFrame, pd.DataFrame]:
    rows: list[dict[str, Any]] = []
    actuals: list[dict[str, Any]] = []
    for index in range(90):
        feature_a = index % 9
        feature_b = (index // 3) % 7
        quantity = (feature_a + 2 * feature_b) % 3
        entity_id = f"train-{index:03d}"
        event_ts = f"2026-01-{1 + index // 30:02d}T{index % 24:02d}:00:00Z"
        rows.append(
            {
                "entity_id": entity_id,
                "event_ts": event_ts,
                "feature_a": feature_a,
                "feature_b": feature_b,
            }
        )
        actuals.append(
            {
                "entity_id": entity_id,
                "event_ts": event_ts,
                "actual_quantity": quantity,
            }
        )
    return pd.DataFrame(rows), pd.DataFrame(actuals)


def _scoring_data(*, drift: bool) -> pd.DataFrame:
    if drift:
        rows = [("score-A", 18, 14), ("score-B", 18, 14), ("score-C", 18, 14)]
    else:
        rows = [("score-A", 1, 2), ("score-B", 4, 5), ("score-C", 7, 1)]
    return pd.DataFrame(
        [
            {
                "entity_id": entity_id,
                "event_ts": "2026-02-01T00:00:00Z",
                "feature_a": feature_a,
                "feature_b": feature_b,
            }
            for entity_id, feature_a, feature_b in rows
        ]
    )


def _train_model(
    features: pd.DataFrame, actuals: pd.DataFrame
) -> tuple[RandomForestClassifier, dict[str, float]]:
    labeled = label_actuals(actuals, _CONTRACT)
    training = features.merge(
        labeled[["entity_id", "event_ts", "quantity_class"]],
        on=["entity_id", "event_ts"],
        how="inner",
        validate="one_to_one",
    )
    model = RandomForestClassifier(n_estimators=80, max_depth=8, random_state=17)
    inputs = training[["feature_a", "feature_b"]]
    labels = training["quantity_class"]
    model.fit(inputs, labels)
    probabilities = model.predict_proba(inputs)
    predicted = model.predict(inputs)
    metrics = {
        "macro_f1": float(f1_score(labels, predicted, average="macro")),
        "log_loss": float(log_loss(labels, probabilities, labels=list(model.classes_))),
    }
    return model, metrics


def _total_variation(reference: list[str], current: list[str]) -> float:
    classes = sorted(set(reference) | set(current))
    reference_total = len(reference)
    current_total = len(current)
    return 0.5 * sum(
        abs(reference.count(label) / reference_total - current.count(label) / current_total)
        for label in classes
    )


def _result(
    scenario: Scenario,
    terminal_state: str,
    *,
    gate_outcome: PromotionOutcome | None = None,
    gate_reasons: tuple[str, ...] = (),
    selected_model_version: str | None = None,
    prediction_rows: tuple[dict[str, str], ...] = (),
    monitor_alert: bool = False,
    technical_error: str | None = None,
) -> ScenarioResult:
    return ScenarioResult(
        scenario=scenario.value,
        terminal_state=terminal_state,
        gate_outcome=gate_outcome.value if gate_outcome is not None else None,
        gate_reasons=gate_reasons,
        selected_model_version=selected_model_version,
        prediction_rows=prediction_rows,
        monitor_alert=monitor_alert,
        technical_error=technical_error,
    )


def run_scenario(scenario: Scenario) -> ScenarioResult:
    """Run one deterministic lifecycle scenario without cloud credentials."""
    training_features, actuals = _training_data()
    if scenario is Scenario.INVALID_LABEL:
        actuals["actual_quantity"] = actuals["actual_quantity"].astype(float)
        actuals.loc[0, "actual_quantity"] = 1.5
        try:
            label_actuals(actuals, _CONTRACT)
        except ContractViolation as error:
            return _result(
                scenario,
                "HALTED",
                gate_outcome=PromotionOutcome.HALT,
                gate_reasons=(str(error),),
            )
        raise AssertionError("invalid-label fixture unexpectedly passed")

    model, candidate_metrics = _train_model(training_features, actuals)
    champion_metrics = {"macro_f1": 0.78, "log_loss": 0.62}
    champion_model = DummyClassifier(strategy="constant", constant="1").fit(
        training_features[["feature_a", "feature_b"]],
        label_actuals(actuals, _CONTRACT)["quantity_class"],
    )
    if scenario is Scenario.WEAK_CANDIDATE:
        candidate_metrics = {"macro_f1": 0.52, "log_loss": 1.10}

    decision = evaluate_promotion(
        candidate_metrics,
        champion_metrics,
        _RULES,
        has_production_deployment=True,
    )
    selected_version = "2" if decision.outcome is PromotionOutcome.PROMOTE else "1"
    selected_model = model if decision.outcome is PromotionOutcome.PROMOTE else champion_model
    if scenario is Scenario.TECHNICAL_FAILURE:
        return _result(
            scenario,
            "FAILED",
            gate_outcome=decision.outcome,
            gate_reasons=decision.reasons,
            selected_model_version=selected_version,
            technical_error="simulated batch endpoint invocation failure",
        )

    scoring = _scoring_data(drift=scenario is Scenario.DRIFT)
    validate_scoring_population(scoring)
    predicted = [
        str(value) for value in selected_model.predict(scoring[["feature_a", "feature_b"]])
    ]
    rows = tuple(
        {
            "prediction_id": prediction_id(
                source_batch_id="batch-2026-02-01",
                entity_id=str(row.entity_id),
                correlation_id=f"actual-{row.entity_id}-{row.event_ts}",
                prediction_ts=str(row.event_ts),
                model_name="quantity-model",
                model_version=selected_version,
                mapping_version=_CONTRACT.mapping_version,
            ),
            "entity_id": str(row.entity_id),
            "prediction_class": prediction_class,
            "model_version": selected_version,
            "mapping_version": _CONTRACT.mapping_version,
        }
        for row, prediction_class in zip(scoring.itertuples(index=False), predicted, strict=True)
    )
    reference_predictions = [
        str(value)
        for value in selected_model.predict(training_features[["feature_a", "feature_b"]])
    ]
    monitor_alert = _total_variation(reference_predictions, predicted) >= 0.50
    terminal = (
        "PROMOTED_AND_PUBLISHED"
        if decision.outcome is PromotionOutcome.PROMOTE
        else "RETAINED_AND_PUBLISHED"
    )
    return _result(
        scenario,
        terminal,
        gate_outcome=decision.outcome,
        gate_reasons=decision.reasons,
        selected_model_version=selected_version,
        prediction_rows=rows,
        monitor_alert=monitor_alert,
    )


def _parse_scenarios(value: str) -> tuple[Scenario, ...]:
    if value == "all":
        return tuple(Scenario)
    try:
        return (Scenario(value),)
    except ValueError as error:
        choices = ", ".join(["all", *(scenario.value for scenario in Scenario)])
        raise argparse.ArgumentTypeError(f"scenario must be one of: {choices}") from error


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", default="all")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    scenarios = _parse_scenarios(args.scenario)
    results = [run_scenario(scenario) for scenario in scenarios]
    payload = json.dumps([asdict(result) for result in results], indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.mkdir(parents=True, exist_ok=True)
        (args.output / "scenario-results.json").write_text(payload, encoding="utf-8")
    print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
