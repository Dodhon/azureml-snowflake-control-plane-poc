from __future__ import annotations

import pandas as pd
import pytest

from azureml_snowflake_poc.components.publish import reconcile_prediction_keys
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
    assert "target.CREATED_AT = source.CREATED_AT" not in rendered
    assert "target.UPDATED_AT = source.UPDATED_AT" in rendered
    assert "WHEN NOT MATCHED THEN INSERT" in rendered


def test_publication_rejects_predictions_from_another_source_batch() -> None:
    # Contract: endpoint output must preserve the source batch as well as row correlation keys.
    # Edge: stale or misrouted deployment output cannot be published under a different batch.
    features = pd.DataFrame(
        {
            "entity": ["A"],
            "feature_ts": ["2026-01-01T00:00:00Z"],
            "source_batch_id": ["batch-1"],
            "correlation_id": ["event-1"],
        }
    )
    predictions = pd.DataFrame(
        {
            "entity_id": ["A"],
            "prediction_ts": ["2026-01-01T00:00:00Z"],
            "source_batch_id": ["batch-2"],
            "correlation_id": ["event-1"],
        }
    )

    with pytest.raises(ValueError, match="reconciliation failed"):
        reconcile_prediction_keys(
            features,
            predictions,
            entity_column="entity",
            timestamp_column="feature_ts",
            correlation_column="correlation_id",
        )


def test_publication_rejects_untrusted_identifiers() -> None:
    # Contract: deployment configuration supplies identifiers, never executable SQL fragments.
    # Edge: identifier injection fails before opening a Snowflake transaction.
    with pytest.raises(ValueError, match="identifier"):
        build_merge_statements(
            target_table="POC.ML.PREDICTIONS; DROP TABLE SOURCE_DATA",
            staging_table="POC.ML.STAGE",
        )
