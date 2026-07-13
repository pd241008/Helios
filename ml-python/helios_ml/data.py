"""
3.1 — Data Loading (Polars)

Lazy-loads all year/split-partitioned Parquet files from the Scala pipeline
via pl.scan_parquet, validates the required columns, logs partition counts,
and drops rows with a null target.
"""

from __future__ import annotations

from pathlib import Path

import polars as pl

REQUIRED_COLS: tuple[str, ...] = (
    "lon",
    "lat",
    "ndvi",
    "lst",
    "split",
    "year",
)


def scan_dense_matrix(data_dir: str | Path) -> pl.LazyFrame:
    """Return a lazy frame over all Parquet part-files under *data_dir*.

    The Scala pipeline writes one part-file per hive partition (year/split),
    so ``**/*.parquet`` picks them all up.  ``hive_partitioning=True``
    reconstructs ``year`` and ``split`` columns from directory names.
    """
    data_path = Path(data_dir)
    parquet_files = sorted(data_path.glob("**/*.parquet"))
    if not parquet_files:
        msg = f"No .parquet files found under {data_path}"
        raise FileNotFoundError(msg)

    return pl.scan_parquet(parquet_files, hive_partitioning=True)


def validate_schema(lf: pl.LazyFrame) -> None:
    """Assert that all REQUIRED_COLS exist in the lazy frame's schema."""
    schema_cols = set(lf.collect_schema().names())
    missing = [c for c in REQUIRED_COLS if c not in schema_cols]
    if missing:
        available = ", ".join(sorted(schema_cols))
        msg = f"Missing required columns: {missing}. Available: {available}"
        raise ValueError(msg)


def log_partition_counts(df: pl.DataFrame) -> None:
    """Print row counts grouped by year and split."""
    counts = df.group_by(["year", "split"]).agg(pl.len().alias("count")).sort("year", "split")
    print("  Partition counts (year / split):")
    for row in counts.iter_rows():
        print(f"    year={row[0]}, split={row[1]}: {row[2]} rows")
    total = df.shape[0]
    print(f"  Total rows: {total}")


def load(data_dir: str | Path) -> tuple[pl.DataFrame, pl.DataFrame]:
    """Load and validate the dense matrix.

    Returns
    -------
    (full_df, feature_df)
        *full_df* retains all columns (including the target and split marker).
        *feature_df* drops the target column but keeps all engineered features
        so the caller can align train/test splits.
    """
    lf = scan_dense_matrix(data_dir)
    validate_schema(lf)

    # Drop rows where the target (split-window LST) is null.
    lf = lf.drop_nulls("lst")
    df = lf.collect()

    log_partition_counts(df)

    return df, df.drop("lst")
