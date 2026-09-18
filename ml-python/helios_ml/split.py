"""
3.2 — Temporal Split

Respects the ``split`` marker column already written by the Scala pipeline
(years 1-8 → train, years 9-10 → test).  Falls back to a date-based split
with a warning if the marker is missing.  Never shuffles across years.
"""

from __future__ import annotations

from typing import Literal

import polars as pl

TRAIN_LABEL = "train"
TEST_LABEL = "test"

SplitStrategy = Literal["marker", "dynamic"]


def temporal_split(
    features: pl.DataFrame,
    target: pl.Series,
    *,
    split_col: str = "split",
    year_col: str = "year",
    train_years: tuple[int, int] | None = (2024, 2031),
    test_years: tuple[int, int] | None = (2032, 2033),
    strategy: SplitStrategy = "marker",
) -> tuple[pl.DataFrame, pl.DataFrame, pl.Series, pl.Series]:
    """Split data into train/test respecting the temporal marker column.

    Parameters
    ----------
    features
        Feature DataFrame (must contain *split_col* or *year_col*).
    target
        Target series (LST).
    split_col
        Name of the column holding "train" / "test" labels.
    year_col
        Fallback year column used if *split_col* is missing.
    train_years, test_years
        Inclusive (start, end) year ranges for the fallback (unused in dynamic 12-month split).
    strategy
        - ``"marker"``: honour the pipeline-written ``split`` column when present,
          falling back to the dynamic 12-month boundary otherwise.
        - ``"dynamic"``: always use the rolling 12-month test window
          (test = strictly later than latest_scene_date − 365 days), ignoring
          any static marker column.

    Returns
    -------
    (X_train, X_test, y_train, y_test)
    """
    if strategy == "dynamic":
        return _split_by_last_12_months(features, target)

    if split_col in features.columns:
        return _split_by_marker(features, target, split_col)

    print(
        f"  WARNING: '{split_col}' column not found — "
        f"falling back to dynamic 12-month test boundary based on latest available scene."
    )
    return _split_by_last_12_months(features, target)


def _split_by_marker(
    features: pl.DataFrame,
    target: pl.Series,
    split_col: str,
) -> tuple[pl.DataFrame, pl.DataFrame, pl.Series, pl.Series]:
    train_mask = features[split_col] == TRAIN_LABEL
    test_mask = features[split_col] == TEST_LABEL

    X_train = features.filter(train_mask).drop(split_col)
    X_test = features.filter(test_mask).drop(split_col)
    y_train = target.filter(train_mask)
    y_test = target.filter(test_mask)

    n_train = len(X_train)
    n_test = len(X_test)
    unlabelled = len(features) - n_train - n_test

    print(f"  Temporal split: {n_train} train / {n_test} test", end="")
    if unlabelled:
        print(f"  ({unlabelled} unlabelled rows dropped)")
    else:
        print()

    return X_train, X_test, y_train, y_test


def _split_by_last_12_months(
    features: pl.DataFrame,
    target: pl.Series,
) -> tuple[pl.DataFrame, pl.DataFrame, pl.Series, pl.Series]:
    from datetime import timedelta
    # 1. Reconstruct approximate datetime for each row from year and doy
    df = features.with_columns([
        (
            pl.datetime(pl.col("year"), 1, 1) + pl.duration(days=pl.col("doy") - 1)
        ).alias("_exact_date")
    ])
    
    # 2. Find the absolute latest date in the entire dataset
    max_date = df.select(pl.max("_exact_date")).item()
    cutoff_date = max_date - timedelta(days=365)
    
    # 3. Apply the 12-month test boundary
    train_mask = pl.col("_exact_date") <= cutoff_date
    test_mask = pl.col("_exact_date") > cutoff_date
    
    X_train = df.filter(train_mask).drop("_exact_date", strict=False)
    X_test = df.filter(test_mask).drop("_exact_date", strict=False)
    
    # Also filter target using the boolean mask directly against the series
    train_series_mask = df.select(train_mask).get_column("_exact_date")
    test_series_mask = df.select(test_mask).get_column("_exact_date")
    
    y_train = target.filter(train_series_mask)
    y_test = target.filter(test_series_mask)

    print(f"  Dynamic 12-mo split (cutoff {cutoff_date.date()}): {len(X_train)} train / {len(X_test)} test")

    return X_train, X_test, y_train, y_test
