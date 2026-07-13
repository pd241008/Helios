"""Tests for spatial sampling functions in helios_ml.data."""

from __future__ import annotations

import math

import polars as pl

from helios_ml.data import (
    _stratified_zoning_sample,
    _systematic_grid_sample,
    load,
)

# ════════════════════════════════════════════════════════════════════
#  Fixtures
# ════════════════════════════════════════════════════════════════════

def _make_grid(n_lon: int = 10, n_lat: int = 10, n_years: int = 2) -> pl.LazyFrame:
    """Build a synthetic spatial grid as a LazyFrame.

    Creates n_lon × n_lat pixels per year with distinct lon/lat values,
    mimicking the structure of the real dense matrix.
    """
    rows = []
    for year in range(2024, 2024 + n_years):
        for i in range(n_lon):
            for j in range(n_lat):
                rows.append({
                    "lon": 80.0 + i * 0.003,  # ~30m spacing
                    "lat": 13.0 + j * 0.003,
                    "lst": 300.0 + i + j,
                    "ndvi": 0.5 + i * 0.01,
                    "year": year,
                    "split": "train",
                })
    return pl.DataFrame(rows).lazy()


def _make_zoned_grid(
    n_per_zone: int = 30,
    n_years: int = 2,
) -> pl.LazyFrame:
    """Build a synthetic grid with zoning categories for stratified tests."""
    zones = ["residential", "commercial", "industrial", "green"]
    rows = []
    for year in range(2024, 2024 + n_years):
        for zi, zone in enumerate(zones):
            for k in range(n_per_zone):
                rows.append({
                    "lon": 80.0 + k * 0.003,
                    "lat": 13.0 + zi * 0.01 + k * 0.003,
                    "lst": 300.0 + k,
                    "ndvi": 0.5,
                    "year": year,
                    "split": "train",
                    "zoning_category": zone,
                })
    return pl.DataFrame(rows).lazy()


# ════════════════════════════════════════════════════════════════════
#  Systematic grid sampling
# ════════════════════════════════════════════════════════════════════

class TestSystematicGridSample:
    def test_rate_one_returns_all(self) -> None:
        lf = _make_grid()
        result = _systematic_grid_sample(lf, 1.0).collect()
        assert result.shape[0] == lf.collect().shape[0]

    def test_rate_zero_returns_all(self) -> None:
        lf = _make_grid()
        result = _systematic_grid_sample(lf, 0.0).collect()
        assert result.shape[0] == lf.collect().shape[0]

    def test_step_math(self) -> None:
        """Verify step = round(1/sqrt(rate)) gives expected values."""
        assert max(1, round(1.0 / math.sqrt(0.1))) == 3  # ~11%
        assert max(1, round(1.0 / math.sqrt(0.05))) == 4  # ~6%
        assert max(1, round(1.0 / math.sqrt(0.25))) == 2  # ~25%
        assert max(1, round(1.0 / math.sqrt(0.5))) == 1  # ~100%

    def test_achieved_fraction_01(self) -> None:
        """rate=0.1 → step=3 → expect ~1/9 ≈ 11% of rows kept."""
        lf = _make_grid(n_lon=9, n_lat=9, n_years=1)
        n_before = lf.select(pl.len()).collect().item()
        result = _systematic_grid_sample(lf, 0.1).collect()
        n_after = result.shape[0]
        achieved = n_after / n_before
        # With 9 distinct lon and 9 distinct lat, step=3 keeps 3×3 = 9
        # out of 81 pixels → 9/81 ≈ 11.1%
        assert 0.08 <= achieved <= 0.15, f"Achieved {achieved:.3f}, expected ~0.11"

    def test_achieved_fraction_25(self) -> None:
        """rate=0.25 → step=2 → expect ~1/4 ≈ 25% of rows kept."""
        lf = _make_grid(n_lon=8, n_lat=8, n_years=1)
        n_before = lf.select(pl.len()).collect().item()
        result = _systematic_grid_sample(lf, 0.25).collect()
        n_after = result.shape[0]
        achieved = n_after / n_before
        # step=2, 4 distinct lon × 4 distinct lat = 16 out of 64 → 25%
        assert 0.20 <= achieved <= 0.30, f"Achieved {achieved:.3f}, expected ~0.25"

    def test_per_year_independence(self) -> None:
        """Each year should be sampled independently."""
        lf = _make_grid(n_lon=9, n_lat=9, n_years=2)
        result = _systematic_grid_sample(lf, 0.1).collect()
        year_counts = result.group_by("year").agg(pl.len().alias("count"))
        # Both years should have the same count (same grid dimensions)
        counts = year_counts["count"].to_list()
        assert counts[0] == counts[1], f"Year counts differ: {counts}"

    def test_deterministic(self) -> None:
        """Two calls produce identical results."""
        lf = _make_grid()
        r1 = _systematic_grid_sample(lf, 0.1).collect()
        r2 = _systematic_grid_sample(lf, 0.1).collect()
        assert r1.equals(r2)

    def test_lazy_chain_no_collect(self) -> None:
        """Verify the function returns a LazyFrame, not a DataFrame."""
        lf = _make_grid()
        result = _systematic_grid_sample(lf, 0.1)
        assert isinstance(result, pl.LazyFrame)


# ════════════════════════════════════════════════════════════════════
#  Stratified zoning sampling
# ════════════════════════════════════════════════════════════════════

class TestStratifiedZoningSample:
    def test_rate_one_returns_all(self) -> None:
        lf = _make_zoned_grid()
        result = _stratified_zoning_sample(lf, 1.0).collect()
        assert result.shape[0] == lf.collect().shape[0]

    def test_preserves_category_proportions(self) -> None:
        """Each zone should be sampled at roughly the same rate."""
        lf = _make_zoned_grid(n_per_zone=100, n_years=1)
        n_before = lf.select(pl.len()).collect().item()

        result = _stratified_zoning_sample(lf, 0.2).collect()
        n_after = result.shape[0]
        overall_rate = n_after / n_before

        # Check per-zone rates
        before_counts = (
            lf.collect().group_by("zoning_category").agg(pl.len().alias("before"))
        )
        after_counts = result.group_by("zoning_category").agg(pl.len().alias("after"))
        merged = before_counts.join(after_counts, on="zoning_category")
        merged = merged.with_columns(
            (pl.col("after") / pl.col("before")).alias("zone_rate")
        )

        for row in merged.iter_rows(named=True):
            zone_rate = row["zone_rate"]
            # Each zone's rate should be within ±5pp of the overall rate
            assert abs(zone_rate - overall_rate) < 0.10, (
                f"Zone '{row['zoning_category']}' rate {zone_rate:.3f} "
                f"deviates from overall {overall_rate:.3f}"
            )

    def test_no_zoning_col_falls_back(self) -> None:
        """Without a zoning column, should fall back to grid sampling."""
        lf = _make_grid(n_lon=9, n_lat=9, n_years=1)
        n_before = lf.select(pl.len()).collect().item()
        result = _stratified_zoning_sample(lf, 0.1).collect()
        n_after = result.shape[0]
        achieved = n_after / n_before
        # Falls back to grid, so ~11%
        assert 0.05 <= achieved <= 0.20, f"Fallback achieved {achieved:.3f}"

    def test_per_year_independence(self) -> None:
        """Each year should be sampled independently."""
        lf = _make_zoned_grid(n_per_zone=30, n_years=2)
        result = _stratified_zoning_sample(lf, 0.25).collect()
        year_counts = result.group_by("year").agg(pl.len().alias("count"))
        counts = year_counts["count"].to_list()
        assert counts[0] == counts[1], f"Year counts differ: {counts}"

    def test_lazy_chain_no_collect(self) -> None:
        lf = _make_zoned_grid()
        result = _stratified_zoning_sample(lf, 0.2)
        assert isinstance(result, pl.LazyFrame)


# ════════════════════════════════════════════════════════════════════
#  Full loader integration
# ════════════════════════════════════════════════════════════════════

class TestLoadIntegration:
    def test_full_resolution_no_sampling(self, tmp_path) -> None:
        """full_resolution=True should not reduce row count."""
        # Write a small parquet dataset
        df = _make_grid(n_lon=5, n_lat=5, n_years=1).collect()
        # Add required columns
        df = df.with_columns([
            pl.lit(0.0).alias("bt10_minus_bt11"),
            pl.lit("2024-01-01").alias("acquisition_date"),
            pl.lit("tile_1").alias("tile_id"),
        ])
        year_dir = tmp_path / "year=2024" / "split=train"
        year_dir.mkdir(parents=True)
        df.write_parquet(year_dir / "part-0.parquet")

        full_df, feat_df = load(tmp_path, full_resolution=True)
        assert full_df.shape[0] == 25  # 5×5 grid

    def test_sampling_reduces_rows(self, tmp_path) -> None:
        """full_resolution=False with systematic-grid should reduce rows."""
        df = _make_grid(n_lon=9, n_lat=9, n_years=1).collect()
        df = df.with_columns([
            pl.lit(0.0).alias("bt10_minus_bt11"),
            pl.lit("2024-01-01").alias("acquisition_date"),
            pl.lit("tile_1").alias("tile_id"),
        ])
        year_dir = tmp_path / "year=2024" / "split=train"
        year_dir.mkdir(parents=True)
        df.write_parquet(year_dir / "part-0.parquet")

        full_df, feat_df = load(
            tmp_path,
            full_resolution=False,
            sample_strategy="systematic-grid",
            sample_rate=0.1,
        )
        # 9×9 = 81 pixels, step=3 → 3×3 = 9 kept
        assert full_df.shape[0] < 81
        assert full_df.shape[0] == 9
