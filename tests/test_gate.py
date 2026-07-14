from __future__ import annotations

from azureml_snowflake_poc.gate import MetricRule, PromotionOutcome, evaluate_promotion

RULES = (
    MetricRule(name="macro_f1", direction="maximize", threshold=0.70, minimum_delta=0.01),
    MetricRule(name="log_loss", direction="minimize", threshold=0.80, minimum_delta=0.01),
)


def test_candidate_promotes_only_when_every_rule_passes() -> None:
    # Contract: promotion needs complete evidence and every comparison rule.
    # Edge: one failed rule retains the exact current deployment.
    candidate = {"macro_f1": 0.82, "log_loss": 0.41}
    champion = {"macro_f1": 0.79, "log_loss": 0.44}

    decision = evaluate_promotion(candidate, champion, RULES, has_production_deployment=True)

    assert decision.outcome is PromotionOutcome.PROMOTE
    assert decision.reasons == ()


def test_missing_metric_is_unknown_and_retains() -> None:
    # Contract: unknown is red at promotion gates; missing metrics never become implicit passes.
    # Edge: incomplete candidate evidence retains an existing production deployment.
    decision = evaluate_promotion(
        {"macro_f1": 0.82},
        {"macro_f1": 0.79, "log_loss": 0.44},
        RULES,
        has_production_deployment=True,
    )

    assert decision.outcome is PromotionOutcome.RETAIN
    assert "missing candidate metric: log_loss" in decision.reasons


def test_first_weak_candidate_halts_without_production_model() -> None:
    # Contract: RETAIN requires an exact existing production deployment to score.
    # Edge: the first weak candidate halts instead of scoring an unapproved model.
    decision = evaluate_promotion(
        {"macro_f1": 0.50, "log_loss": 1.20},
        None,
        RULES,
        has_production_deployment=False,
    )

    assert decision.outcome is PromotionOutcome.HALT
    assert "no production deployment is available" in decision.reasons
