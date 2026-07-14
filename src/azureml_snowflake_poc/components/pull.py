"""Pull immutable scoring, training-feature, and actual snapshots from Snowflake."""

from __future__ import annotations

import argparse
import hashlib
from datetime import UTC, datetime
from pathlib import Path

from azureml_snowflake_poc.component_io import write_json, write_parquet
from azureml_snowflake_poc.configuration import load_configuration, require
from azureml_snowflake_poc.snowflake_io import connect, fetch_dataframe, validate_read_query


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--source-batch-id", required=True)
    parser.add_argument("--source-cutoff", required=True)
    parser.add_argument("--source-event-id", default="manual")
    parser.add_argument("--training-features-output", type=Path, required=True)
    parser.add_argument("--scoring-output", type=Path, required=True)
    parser.add_argument("--actuals-output", type=Path, required=True)
    parser.add_argument("--manifest-output", type=Path, required=True)
    args = parser.parse_args()

    config = load_configuration(args.config)
    source_query = validate_read_query(require(config, "snowflake.source_query"))
    training_features_query = validate_read_query(
        require(config, "snowflake.training_features_query")
    )
    actuals_query = validate_read_query(require(config, "snowflake.actuals_query"))
    query_tag = {
        "component": "pull_snowflake",
        "source_batch_id": args.source_batch_id,
        "source_cutoff": args.source_cutoff,
        "source_event_id": args.source_event_id,
    }
    parameters = {
        "source_batch_id": args.source_batch_id,
        "source_cutoff": args.source_cutoff,
    }
    connection = connect(config)
    try:
        scoring = fetch_dataframe(
            connection, source_query, query_tag=query_tag, parameters=parameters
        )
        training_features = fetch_dataframe(
            connection,
            training_features_query,
            query_tag=query_tag,
            parameters=parameters,
        )
        actuals = fetch_dataframe(
            connection, actuals_query, query_tag=query_tag, parameters=parameters
        )
    finally:
        connection.close()

    if "source_batch_id" not in scoring.columns:
        scoring["source_batch_id"] = args.source_batch_id
    elif not scoring["source_batch_id"].astype(str).eq(args.source_batch_id).all():
        raise ValueError("source query returned rows outside the requested source_batch_id")
    write_parquet(scoring, args.scoring_output, "scoring.parquet")
    write_parquet(training_features, args.training_features_output, "training-features.parquet")
    write_parquet(actuals, args.actuals_output, "actuals.parquet")
    write_json(
        args.manifest_output,
        {
            "actuals_query_sha256": hashlib.sha256(actuals_query.encode()).hexdigest(),
            "actuals_rows": len(actuals),
            "created_at": datetime.now(UTC).isoformat(),
            "scoring_query_sha256": hashlib.sha256(source_query.encode()).hexdigest(),
            "source_event_id": args.source_event_id,
            "training_features_query_sha256": hashlib.sha256(
                training_features_query.encode()
            ).hexdigest(),
            "training_features_rows": len(training_features),
            "scoring_rows": len(scoring),
            "source_batch_id": args.source_batch_id,
            "source_cutoff": args.source_cutoff,
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
