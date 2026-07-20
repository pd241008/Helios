"""
3.1 — Data Loading (Polars)

Lazy-loads all year/split-partitioned Parquet files from the Scala pipeline
via pl.scan_parquet, validates the required columns, logs partition counts,
and drops rows with a null target.

Optional spatial sampling (``full_resolution=False``) reduces training
compute cost by exploiting spatial autocorrelation in adjacent 30m Landsat
pixels.  Sampling is applied independently within each year partition so
temporal coverage is never skewed.  Heatmap / analysis code should always
use ``full_resolution=True`` (the default).

All sampling operations are expressed as lazy Polars expressions (window
functions via ``.over()``) so the full dataset is never materialised before
the final ``.collect()``.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Literal

import polars as pl

REQUIRED_COLS: tuple[str, ...] = (
    "lon",
    "lat",
    "ndvi",
    "lst",
    "split",
    "year",
    "doy",
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


def log_partition_counts(df: pl.DataFrame, label: str = "") -> None:
    """Print row counts grouped by year and split."""
    prefix = f"  [{label}] " if label else "  "
    counts = df.group_by(["year", "split"]).agg(pl.len().alias("count")).sort("year", "split")
    print(f"{prefix}Partition counts (year / split):")
    for row in counts.iter_rows():
        print(f"{prefix}  year={row[0]}, split={row[1]}: {row[2]} rows")
    total = df.shape[0]
    print(f"{prefix}Total rows: {total}")


# ════════════════════════════════════════════════════════════════════
#  Spatial sampling — lazy Polars expressions
# ════════════════════════════════════════════════════════════════════

def _systematic_grid_sample(lf: pl.LazyFrame, rate: float) -> pl.LazyFrame:
    """Keep every Nth pixel on a spatial grid within each year partition.

    The step size ``N`` is derived from ``rate`` so that approximately
    ``rate`` fraction of rows are kept.  Because a 2-D grid uses
    ``N × N`` neighbourhoods, the actual fraction is ``≈ 1/N²``.
    We pick ``N = max(1, round(1 / sqrt(rate)))`` so that a target rate
    of 0.1 yields N=3 → ~1/9 ≈ 11% kept.

    Pixels are ranked by their rounded (lon, lat) position within each
    year partition to create a deterministic spatial grid independent of
    row order.  All operations are lazy window functions.
    """
    if rate >= 1.0 or rate <= 0.0:
        return lf

    step = max(1, round(1.0 / math.sqrt(rate)))

    # rank("dense").over("year") assigns a sequential integer to each
    # distinct lon/lat value within each year — no collect needed.
    # No rounding: 30m Landsat pixels have unique coordinates per year,
    # and rounding to 2dp would collapse ~30m spacing into ~1km bins.
    return (
        lf.with_columns([
            pl.col("lon").rank("dense").over("year").alias("_grid_lon"),
            pl.col("lat").rank("dense").over("year").alias("_grid_lat"),
        ])
        .with_columns([
            (pl.col("_grid_lon") % step).alias("_mod_lon"),
            (pl.col("_grid_lat") % step).alias("_mod_lat"),
        ])
        .filter((pl.col("_mod_lon") == 0) & (pl.col("_mod_lat") == 0))
        .drop(["_grid_lon", "_grid_lat", "_mod_lon", "_mod_lat"])
    )


def _stratified_zoning_sample(lf: pl.LazyFrame, rate: float) -> pl.LazyFrame:
    """Sample proportionally within each zoning category per year.

    Preserves category balance by sampling ``rate`` fraction from every
    zoning_category (or ``zoning_target_encoded`` if ``zoning_category``
    is absent) within each year partition.  Uses ``rank("ordinal")`` for
    deterministic row numbering within each (year, zone) group.
    """
    if rate >= 1.0 or rate <= 0.0:
        return lf

    schema = lf.collect_schema().names()
    strat_col = "zoning_category" if "zoning_category" in schema else (
        "zoning_target_encoded" if "zoning_target_encoded" in schema else None
    )

    if strat_col is None:
        return _systematic_grid_sample(lf, rate)

    step = max(1, round(1.0 / rate))

    # rank("ordinal").over("year", strat_col) gives a sequential 1-based
    # row number within each (year, zone) partition — fully lazy.
    return (
        lf.with_columns(
            pl.col("lon").rank("ordinal").over("year", strat_col).alias("_row_idx"),
        )
        .filter(pl.col("_row_idx") % step == 0)
        .drop("_row_idx")
    )


def _apply_sampling(
    lf: pl.LazyFrame,
    sample_strategy: Literal["none", "systematic-grid", "stratified-zoning"],
    sample_rate: float,
) -> pl.LazyFrame:
    """Apply spatial sampling as lazy Polars operations.

    Returns a LazyFrame — no ``.collect()`` call.  The caller decides
    when to materialise.
    """
    if sample_strategy == "none" or sample_rate >= 1.0 or sample_rate <= 0.0:
        return lf

    sample_fn = {
        "systematic-grid": _systematic_grid_sample,
        "stratified-zoning": _stratified_zoning_sample,
    }[sample_strategy]

    return sample_fn(lf, sample_rate)


# ════════════════════════════════════════════════════════════════════
#  Main loader
# ════════════════════════════════════════════════════════════════════

def load(
    data_dir: str | Path,
    *,
    full_resolution: bool = True,
    sample_strategy: Literal["none", "systematic-grid", "stratified-zoning"] = "none",
    sample_rate: float = 0.1,
) -> tuple[pl.DataFrame, pl.DataFrame]:
    """Load and validate the dense matrix.

    Parameters
    ----------
    data_dir
        Path to the staging/dense directory containing Parquet files.
    full_resolution
        When ``True`` (default), returns all rows — used by heatmap /
        analysis code that needs full spatial detail.  When ``False``,
        spatial sampling is applied per *sample_strategy* / *sample_rate*
        to reduce training compute cost.
    sample_strategy
        Spatial sampling strategy (only effective when ``full_resolution=False``):
        - ``"none"``: no sampling, return full data.
        - ``"systematic-grid"``: keep every Nth pixel on a 2-D spatial grid
          (deterministic, ~N² reduction).
        - ``"stratified-zoning"``: sample proportionally within each zoning
          category to preserve class balance.
    sample_rate
        Target fraction of rows to keep (0.0–1.0).  Actual achieved fraction
        may differ slightly for grid/stratified strategies.

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

    # Lazy row count before sampling — triggers only a COUNT scan, not
    # a full materialisation of the 91M-row dataset.
    n_before = lf.select(pl.len()).collect().item()

    if not full_resolution:
        lf = _apply_sampling(lf, sample_strategy, sample_rate)

    # Materialise ONCE — after all filtering / sampling.
    df = lf.collect()

    n_after = df.shape[0]
    achieved = n_after / n_before if n_before > 0 else 0.0

    if not full_resolution:
        print(f"  [sampling] Strategy: {sample_strategy}, target rate: {sample_rate:.2%}")
        print(f"  [sampling] Rows: {n_before:,} → {n_after:,} (achieved: {achieved:.2%})")
        log_partition_counts(df, label="after sampling")
    else:
        print(f"  [full-resolution] No sampling applied — {n_after:,} rows.")

    return df, df.drop("lst")
