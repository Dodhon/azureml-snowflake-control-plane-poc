from __future__ import annotations

import pytest

from azureml_snowflake_poc.snowflake_publish import build_merge_statements


def test_publication_uses_transaction_and_stable_merge_key() -> None:
    # Contract: complete batches publish transactionally; retries update, not duplicate.
    # Edge: the stable prediction ID is the sole merge identity for the product table.
    statements = build_merge_statements(
        target_table="POC.ML.PREDICTIONS",
        staging_table="POC.ML.PREDICTIONS_STAGE_RUN_42",
    )
    rendered = "\n".join(statements)

    assert statements[0] == "BEGIN"
    assert statements[-1] == "COMMIT"
    assert "MERGE INTO POC.ML.PREDICTIONS AS target" in rendered
    assert "target.PREDICTION_ID = source.PREDICTION_ID" in rendered
    assert "WHEN NOT MATCHED THEN INSERT" in rendered


def test_publication_rejects_untrusted_identifiers() -> None:
    # Contract: deployment configuration supplies identifiers, never executable SQL fragments.
    # Edge: identifier injection fails before opening a Snowflake transaction.
    with pytest.raises(ValueError, match="identifier"):
        build_merge_statements(
            target_table="POC.ML.PREDICTIONS; DROP TABLE SOURCE_DATA",
            staging_table="POC.ML.STAGE",
        )
