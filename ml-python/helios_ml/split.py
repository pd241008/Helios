"""
3.2 — Temporal Split

Respects the ``split`` marker column already written by the Scala pipeline
(years 1-8 → train, years 9-10 → test).  Falls back to a date-based split
with a warning if the marker is missing.  Never shuffles across years.
"""

from __future__ import annotations

import polars as pl

TRAIN_LABEL = "train"
TEST_LABEL = "test"


def temporal_split(
    features: pl.DataFrame,
    target: pl.Series,
    *,
    split_col: str = "split",
    year_col: str = "year",
    train_years: tuple[int, int] | None = (2024, 2031),
    test_years: tuple[int, int] | None = (2032, 2033),
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
        Inclusive (start, end) year ranges for the fallback.

    Returns
    -------
    (X_train, X_test, y_train, y_test)
    """
    if split_col in features.columns:
        return _split_by_marker(features, target, split_col)

    print(
        f"  WARNING: '{split_col}' column not found — "
        f"falling back to year-based split [{train_years[0]}-{train_years[1]}] "
        f"train / [{test_years[0]}-{test_years[1]}] test."
    )
    return _split_by_year(features, target, year_col, train_years, test_years)


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


def _split_by_year(
    features: pl.DataFrame,
    target: pl.Series,
    year_col: str,
    train_years: tuple[int, int],
    test_years: tuple[int, int],
) -> tuple[pl.DataFrame, pl.DataFrame, pl.Series, pl.Series]:
    train_mask = features[year_col].is_between(train_years[0], train_years[1])
    test_mask = features[year_col].is_between(test_years[0], test_years[1])

    X_train = features.filter(train_mask).drop(year_col)
    X_test = features.filter(test_mask).drop(year_col)
    y_train = target.filter(train_mask)
    y_test = target.filter(test_mask)

    n_train = len(X_train)
    n_test = len(X_test)
    print(f"  Year-based split: {n_train} train / {n_test} test")

    return X_train, X_test, y_train, y_test
