#!/usr/bin/env python3
"""Generate a version-controlled managed feature-set specification from AML Parquet data."""

from __future__ import annotations

import argparse
from pathlib import Path



def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source-path",
        required=True,
        help="Azure storage glob for AML-engineered Parquet snapshots, for example abfss://.../*.parquet",
    )
    parser.add_argument(
        "--output", type=Path, default=Path("feature_store/featuresets/exact_quantity/spec")
    )
    args = parser.parse_args()
    try:
        from azureml.featurestore import create_feature_set_spec
        from azureml.featurestore.contracts import (
            Column,
            ColumnType,
            DateTimeOffset,
            TimestampColumn,
        )
        from azureml.featurestore.feature_source import ParquetFeatureSource
    except ModuleNotFoundError as error:
        raise SystemExit(
            "azureml-featurestore is required; run this generator on a supported Linux environment"
        ) from error
    specification = create_feature_set_spec(
        source=ParquetFeatureSource(
            path=args.source_path,
            timestamp_column=TimestampColumn(name="feature_ts"),
            source_delay=DateTimeOffset(days=0, hours=1, minutes=0),
        ),
        index_columns=[Column(name="entity_id", type=ColumnType.string)],
        source_lookback=DateTimeOffset(days=30, hours=0, minutes=0),
        temporal_join_lookback=DateTimeOffset(days=30, hours=0, minutes=0),
        infer_schema=True,
    )
    args.output.mkdir(parents=True, exist_ok=True)
    specification.dump(args.output, overwrite=True)
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
