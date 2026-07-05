"""
Memory-efficient data loading using Polars.

Polars uses Apache Arrow columnar format under the hood, providing
zero-copy reads from Parquet and lazy evaluation for predicate pushdown.
This keeps memory usage bounded even on multi-GB dense matrices.
"""

from __future__ import annotations

from pathlib import Path

import polars as pl


def load_dense_matrix(
    data_dir: str | Path,
    target_col: str = "B10_TIR",
    exclude_cols: tuple[str, ...] = ("tile_id", "timestamp"),
) -> tuple[pl.DataFrame, pl.Series]:
    """Load the dense Parquet matrix and split into features / target.

    Args:
        data_dir: Path to directory containing dense Parquet part-files.
        target_col: Name of the target (LST proxy) column.
        exclude_cols: Metadata columns to drop from the feature matrix.

    Returns:
        Tuple of (feature_df, target_series).

    Raises:
        FileNotFoundError: If no Parquet files are found.
        ValueError: If the target column is missing.
    """
    data_path = Path(data_dir)

    # Discover all parquet part-files (Spark output convention).
    parquet_files = sorted(data_path.glob("**/*.parquet"))
    if not parquet_files:
        msg = f"No .parquet files found in {data_path}"
        raise FileNotFoundError(msg)

    # Lazy scan for predicate pushdown and projection optimization.
    lf = pl.scan_parquet(parquet_files)

    # Materialize.
    df = lf.collect()

    if target_col not in df.columns:
        available = ", ".join(df.columns)
        msg = f"Target column '{target_col}' not found. Available: {available}"
        raise ValueError(msg)

    # Separate target from features.
    target = df[target_col]

    drop_cols = [c for c in [target_col, *exclude_cols] if c in df.columns]
    features = df.drop(drop_cols)

    # Convert remaining string columns to categorical codes for XGBoost.
    str_cols = [c for c in features.columns if features[c].dtype == pl.Utf8]
    if str_cols:
        features = features.with_columns(
            [pl.col(c).cast(pl.Categorical).to_physical().alias(c) for c in str_cols]
        )

    return features, target


def load_with_validation(
    data_dir: str | Path,
    min_rows: int = 100,
    max_null_fraction: float = 0.05,
) -> tuple[pl.DataFrame, pl.Series]:
    """Load data with basic quality checks.

    Raises:
        ValueError: If data quality thresholds are violated.
    """
    features, target = load_dense_matrix(data_dir)

    # Row count check.
    if len(features) < min_rows:
        msg = f"Insufficient data: {len(features)} rows (min={min_rows})"
        raise ValueError(msg)

    # Null fraction check per column.
    for col_name in features.columns:
        null_frac = features[col_name].null_count() / len(features)
        if null_frac > max_null_fraction:
            msg = (
                f"Column '{col_name}' has {null_frac:.1%} nulls "
                f"(threshold={max_null_fraction:.1%})"
            )
            raise ValueError(msg)

    return features, target
