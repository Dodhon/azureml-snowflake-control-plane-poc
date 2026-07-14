from __future__ import annotations

import math

import pandas as pd
import pytest

from azureml_snowflake_poc.contracts import (
    ContractViolation,
    QuantityClassContract,
    label_actuals,
    validate_correlation_ids,
    validate_scoring_population,
)


def test_quantity_contract_accepts_only_canonical_domain_values() -> None:
    # Contract: exact quantities are finite non-negative integers inside one versioned domain.
    # Edge: fractional, negative, nonfinite, boolean, and out-of-domain values must be rejected.
    contract = QuantityClassContract(mapping_version="quantity-v1", minimum=0, maximum=3)

    assert [contract.encode(value) for value in (0, 1.0, 3)] == ["0", "1", "3"]
    for invalid in (-1, 1.5, math.inf, math.nan, True, 4):
        with pytest.raises(ContractViolation):
            contract.encode(invalid)


def test_scoring_population_cannot_contain_labels() -> None:
    # Contract: scoring rows have predictors only; actuals supply labels separately.
    # Edge: accidental target leakage fails before feature engineering or training.
    scoring = pd.DataFrame({"entity_id": ["A"], "event_ts": ["2026-01-01"], "actual_class": ["1"]})

    with pytest.raises(ContractViolation, match="label column"):
        validate_scoring_population(scoring)


@pytest.mark.parametrize("values", [[None], [" "], ["same", "same"]])
def test_scoring_correlation_ids_are_complete_and_unique(values: list[object]) -> None:
    # Contract: one durable business-event identity follows each scoring row into monitoring.
    # Edge: null, blank, or duplicate IDs must fail before endpoint invocation or publication.
    scoring = pd.DataFrame({"correlation_id": values})

    with pytest.raises(ContractViolation, match="correlation IDs"):
        validate_correlation_ids(scoring, "correlation_id")


def test_actuals_are_labeled_with_the_declared_mapping_version() -> None:
    # Contract: delayed/historical actuals alone derive canonical classes and mapping evidence.
    # Edge: every labeled row carries the exact mapping version used by training and monitoring.
    actuals = pd.DataFrame({"entity_id": ["A", "B"], "actual_quantity": [0, 2]})
    contract = QuantityClassContract(mapping_version="quantity-v1", minimum=0, maximum=3)

    labeled = label_actuals(actuals, contract)

    assert labeled["quantity_class"].tolist() == ["0", "2"]
    assert labeled["quantity_class_mapping_version"].tolist() == ["quantity-v1"] * 2


def test_mapping_version_mismatch_is_technical_failure() -> None:
    # Contract: class-mapping mismatch is an integration failure, never a policy BLOCK.
    # Edge: stale data/model configuration must fail closed.
    contract = QuantityClassContract(mapping_version="quantity-v2", minimum=0, maximum=3)

    with pytest.raises(ContractViolation, match="mapping version"):
        contract.require_mapping_version("quantity-v1", artifact="candidate model")
