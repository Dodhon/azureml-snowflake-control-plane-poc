from __future__ import annotations

from azureml_snowflake_poc.demo import Scenario, run_scenario


def test_five_scenarios_produce_expected_terminal_contracts() -> None:
    # Contract: the POC demonstrates promote, block, retain, drift, and technical failure.
    # Edge: expected policy outcomes remain distinct from unexpected execution failures.
    expected = {
        Scenario.BEST_CASE: "PROMOTED_AND_PUBLISHED",
        Scenario.INVALID_LABEL: "HALTED",
        Scenario.WEAK_CANDIDATE: "RETAINED_AND_PUBLISHED",
        Scenario.DRIFT: "PROMOTED_AND_PUBLISHED",
        Scenario.TECHNICAL_FAILURE: "FAILED",
    }

    results = {scenario: run_scenario(scenario) for scenario in Scenario}

    assert {scenario: result.terminal_state for scenario, result in results.items()} == expected
    assert results[Scenario.INVALID_LABEL].prediction_rows == ()
    assert results[Scenario.TECHNICAL_FAILURE].prediction_rows == ()
    assert results[Scenario.DRIFT].monitor_alert is True


def test_demo_rerun_is_deterministic() -> None:
    # Contract: identical fixture inputs and versions produce byte-stable decision/output manifests.
    # Edge: rerunning the same logical batch cannot manufacture new prediction identities.
    first = run_scenario(Scenario.BEST_CASE).to_json()
    second = run_scenario(Scenario.BEST_CASE).to_json()

    assert first == second
