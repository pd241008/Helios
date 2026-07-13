"""
Track B — Python-native heatmaps from the dense matrix (offline).

Consumes the already-ingested dense Parquet matrix (staging/dense/) keyed by
lon/lat and generates:

  1. Static PNG heatmaps (matplotlib + scipy grid interpolation) for
     LST_split_window, LST_single_channel, BT10_minus_BT11, and NDVI:
     per-year AND full-decade aggregate.
  2. Interactive HTML heatmaps (folium.HeatMap) for the same variables,
     with a year-faceted layout.
  3. Decadal trend panel: per-year mean spatial plot as a small-multiples grid.
  4. NDVI vs LST_split_window hexbin scatter colored by zoning_category.

All outputs are city-agnostic, driven by configurable bounding box, data directory,
and output directory.

Usage:
    uv run python -m analysis.dataset_heatmaps \
        --data-dir ../staging/dense \
        --output-dir ./reports/heatmaps \
        --bbox 79.9469 12.8000 80.3450 13.2300
"""

from __future__ import annotations

import argparse
import math
from pathlib import Path

import folium

# matplotlib uses non-lazy import since it's already a core dep
import matplotlib
import numpy as np
import polars as pl
from scipy.interpolate import griddata
from scipy.ndimage import gaussian_filter

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.cm import ScalarMappable
from matplotlib.colors import Normalize, TwoSlopeNorm
from matplotlib.gridspec import GridSpec

# ══════════════════════════════════════════════════════════════════
#  Config
# ══════════════════════════════════════════════════════════════════

DEFAULT_BBOX = [79.9469, 12.8000, 80.3450, 13.2300]  # Chennai
DEFAULT_DATA_DIR = "../staging/dense"
DEFAULT_OUTPUT_DIR = "./reports/heatmaps"

WATER_VAPOR_CAVEAT = (
    "Note: split-window LST accuracy depends on atmospheric water vapor. "
    "LST_split_window uses a placeholder constant (~2.0 g/cm²) for w. "
    "See processing-scala/README.md — \"Known limitations\"."
)

VARIABLES = ["LST_split_window", "LST_single_channel", "BT10_minus_BT11", "NDVI"]
COLUMN_MAP = {
    "LST_split_window": "lst",
    "LST_single_channel": "st_b10",
    "BT10_minus_BT11": "bt10_minus_bt11",
    "NDVI": "ndvi",
}
COLUMN_MAP_INV = {v: k for k, v in COLUMN_MAP.items()}

# Per-variable min/max for consistent colorbar across years
GLOBAL_RANGES = {
    "LST_split_window": (270, 320),   # K
    "LST_single_channel": (270, 320),  # K
    "BT10_minus_BT11": (-5, 10),       # K difference
    "NDVI": (-0.5, 1.0),               # unitless
}

COLORS = {
    "LST_split_window": "RdYlBu_r",
    "LST_single_channel": "RdYlBu_r",
    "BT10_minus_BT11": "RdBu",
    "NDVI": "RdYlGn",
}


# ══════════════════════════════════════════════════════════════════
#  Data loading
# ══════════════════════════════════════════════════════════════════

def scan_dense_matrix(data_dir: str | Path) -> pl.LazyFrame:
    return pl.scan_parquet(
        Path(data_dir).glob("**/*.parquet"), hive_partitioning=True
    )


def load_data(data_dir: str | Path) -> pl.DataFrame:
    """Load the dense matrix and basic columns needed for heatmaps."""
    lf = scan_dense_matrix(data_dir)
    required = list(set(COLUMN_MAP.values()) | {"lon", "lat", "year"})
    keep = [c for c in required if c in lf.collect_schema().names()]
    df = lf.select(keep).collect()
    # Map actual column names back to canonical variable names
    rename_map = {}
    for var, col in COLUMN_MAP.items():
        if col in df.columns:
            rename_map[col] = var
    df = df.rename(rename_map)
    df = df.drop_nulls()
    return df


def years_present(df: pl.DataFrame) -> list[int]:
    return sorted(df["year"].unique().to_list())


# ══════════════════════════════════════════════════════════════════
#  Gridding helpers
# ══════════════════════════════════════════════════════════════════

def grid_interpolate(lon, lat, values, bbox=None, grid_size=250):
    """Interpolate scattered lon/lat/values onto a regular grid.

    Returns (grid_lon, grid_lat, grid_val) where grid_val is the
    interpolated 2D array with NaN for no-data locations.
    """
    if bbox is None:
        bbox = DEFAULT_BBOX
    lons = np.linspace(bbox[0], bbox[2], grid_size)
    lats = np.linspace(bbox[1], bbox[3], grid_size)
    grid_lon, grid_lat = np.meshgrid(lons, lats)

    mask = np.isfinite(values)
    if mask.sum() < 2:
        return grid_lon, grid_lat, np.full(grid_lon.shape, np.nan)

    grid_val = griddata(
        (lon[mask], lat[mask]),
        values[mask],
        (grid_lon, grid_lat),
        method="cubic",
    )
    # Optional smoothing
    if grid_val is not None and len(np.unique(grid_val)) > 1:
        grid_val = gaussian_filter(grid_val, sigma=0.5)
    return grid_lon, grid_lat, grid_val


# ══════════════════════════════════════════════════════════════════
#  Track 1: Static PNG Heatmaps
# ══════════════════════════════════════════════════════════════════

def plot_static_heatmap(
    var: str,
    lon, lat, values,
    year_label: str,
    output_dir: Path,
):
    """Plot a single static PNG heatmap for a variable and year/aggregate."""
    grid_lon, grid_lat, grid_val = grid_interpolate(lon, lat, values)

    fig, ax = plt.subplots(figsize=(8, 6))

    vmin, vmax = GLOBAL_RANGES[var]
    cmap = plt.get_cmap(COLORS[var])
    if vmin < 0 and vmax > 0:
        norm = TwoSlopeNorm(0, vmin, vmax)
    else:
        norm = Normalize(vmin, vmax)

    im = ax.pcolormesh(
        grid_lon, grid_lat, grid_val,
        cmap=cmap, norm=norm, shading="auto",
    )
    fig.colorbar(im, ax=ax, label=var)
    if year_label != "decadal":
        ax.set_title(f"{var} - {year_label}")
        fig.suptitle(WATER_VAPOR_CAVEAT, fontsize=8, y=0.94)
    else:
        ax.set_title(f"{var} - Decadal Mean ({year_label})")

    ax.set_xlabel("Longitude")
    ax.set_ylabel("Latitude")

    ext = year_label if year_label != "decadal" else "decadal"
    out_path = output_dir / "static" / f"{var}_{ext}.png"
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  Saved: {out_path}")


def generate_static_heatmaps(df: pl.DataFrame, output_dir: Path, years: list[int]):
    """Generate per-year and decadal static heatmaps for each variable."""
    static_dir = output_dir / "static"
    static_dir.mkdir(parents=True, exist_ok=True)

    for var in VARIABLES:
        if var not in df.columns:
            continue

        # Per-year
        for year in years:
            sub = df.filter(pl.col("year") == year)
            if len(sub) < 2:
                continue
            lon = sub["lon"].to_numpy()
            lat = sub["lat"].to_numpy()
            vals = sub[var].to_numpy()
            plot_static_heatmap(var, lon, lat, vals, str(year), output_dir)

        # Decadal aggregate
        lon = df["lon"].to_numpy()
        lat = df["lat"].to_numpy()
        vals = df[var].to_numpy()
        plot_static_heatmap(var, lon, lat, vals, "decadal", output_dir)


# ══════════════════════════════════════════════════════════════════
#  Track 2: Interactive HTML Heatmaps (folium)
# ══════════════════════════════════════════════════════════════════

def generate_interactive_heatmaps(df: pl.DataFrame, output_dir: Path, years: list[int]):
    """Generate interactive folium heatmaps per year and decadal."""
    interactive_dir = output_dir / "interactive"
    interactive_dir.mkdir(parents=True, exist_ok=True)

    for var in VARIABLES:
        if var not in df.columns:
            continue

        for year in years:
            sub = df.filter(pl.col("year") == year)
            if len(sub) < 2:
                continue
            _plot_folium_heatmap(sub, var, year, interactive_dir)

        # Decadal
        _plot_folium_heatmap(df, var, "decadal", interactive_dir)


def _plot_folium_heatmap(df: pl.DataFrame, var: str, year_label: str | int, output_dir: Path):
    lat = df["lat"].to_numpy()
    lon = df["lon"].to_numpy()
    vals = df[var].to_numpy()

    m = folium.Map(location=[lat.mean(), lon.mean()], zoom_start=12)
    # Prepare data for HeatMap: each row is a tuple (lat, lon, val)
    heat_data = [[float(lat[i]), float(lon[i]), float(vals[i])] for i in range(len(lat))]
    folium.TileLayer("cartodbpositron").add_to(m)

    folium.plugins.HeatMap(
        heat_data,
        radius=15,
        blur=10,
        max_zoom=1,
        name=f"{var} - {year_label}",
    ).add_to(m)

    out_path = output_dir / f"{var}_{year_label}.html"
    m.save(str(out_path))
    print(f"  Interactive heatmap saved: {out_path}")


# ══════════════════════════════════════════════════════════════════
#  Track 3: Decadal trend panel (small multiples)
# ══════════════════════════════════════════════════════════════════

def generate_trend_panel(df: pl.DataFrame, output_dir: Path, years: list[int]):
    """Small-multiples grid showing per-year spatial mean LST on a shared color scale.

    This is the 'deep analysis' deliverable — directly usable in the paper to
    illustrate UHI trend over a decade.
    """
    var = "LST_split_window"
    if var not in df.columns:
        return

    n_years = len(years)
    n_cols = 5
    n_rows = int(math.ceil(n_years / n_cols))

    fig = plt.figure(figsize=(16, 3 * n_rows))
    gs = GridSpec(n_rows, n_cols, figure=fig, hspace=0.5)
    vmin, vmax = GLOBAL_RANGES[var]
    cmap = plt.get_cmap(COLORS[var])

    for idx, year in enumerate(years):
        row = idx // n_cols
        col = idx % n_cols
        ax = fig.add_subplot(gs[row, col])

        sub = df.filter(pl.col("year") == year)
        if sub is None or len(sub) < 2:
            ax.text(0.5, 0.5, "no data", transform=ax.transAxes, ha="center")
            ax.set_title(f"{year}")
            continue

        lon, lat = sub["lon"].to_numpy(), sub["lat"].to_numpy()
        vals = sub[var].to_numpy()
        _, _, grid_val = grid_interpolate(lon, lat, vals)

        ax.pcolormesh(
            np.linspace(DEFAULT_BBOX[0], DEFAULT_BBOX[2], 250),
            np.linspace(DEFAULT_BBOX[1], DEFAULT_BBOX[3], 250),
            grid_val,
            cmap=cmap, vmin=vmin, vmax=vmax,
            shading="auto",
        )
        ax.set_title(f"{year}", fontsize=10)

        n_mean = sub[var].mean()
        ax.annotate(f"μ={n_mean:.1f}", xy=(0.95, 0.05), ha="right",
                     fontsize=8, color="white", transform=ax.transAxes,
                     bbox=dict(boxstyle="round,pad=0.2", facecolor="black", alpha=0.5))
        ax.set_xticks([])
        ax.set_yticks([])

    # Add colorbar
    fig.subplots_adjust(bottom=0.1)
    cbar_ax = fig.add_axes([0.2, 0.02, 0.6, 0.03])
    fig.colorbar(ScalarMappable(cmap=cmap, norm=Normalize(vmin, vmax)),
                 cax=cbar_ax, orientation="horizontal")

    fig.text(0.5, 0.94, "LST Split Window - Decadal Trend Panel",
             ha="center", fontsize=14, weight="bold")
    fig.suptitle(WATER_VAPOR_CAVEAT, fontsize=8, y=0.90)

    out_path = output_dir / "static" / "trend_panel_LST_split_window.png"
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  Trend panel saved: {out_path}")


# ══════════════════════════════════════════════════════════════════
#  Track 4: NDVI vs LST hexbin
# ══════════════════════════════════════════════════════════════════

def generate_ndvi_vs_lst_hexbin(df: pl.DataFrame, output_dir: Path):
    """Hexbin scatter of NDVI vs LST_split_window colored by zoning_category.

    This is core UHI relationship — the literature review anchor plot.
    """
    if "NDVI" not in df.columns or "LST_split_window" not in df.columns:
        return

    ndvi = df["NDVI"].to_numpy()
    lst = df["LST_split_window"].to_numpy()

    zoning = (df["zoning_category_encoded"].to_numpy()
              if "zoning_category_encoded" in df.columns else None)

    fig, ax = plt.subplots(figsize=(10, 8))
    cb = ax.hexbin(
        ndvi, lst,
        C=zoning,
        gridsize=30,
        cmap="Spectral_r",
        reduce_C_function=np.mean,
        mincnt=1,
        edgecolors="grey",
        linewidth=0.5,
    )
    cb_label = "zoning_category_encoded" if zoning is not None else "count"
    fig.colorbar(cb, ax=ax, label=cb_label)

    ax.set_xlabel("NDVI")
    ax.set_ylabel("LST_split_window (K)")
    ax.set_title("NDVI vs LST_split_window colored by Zoning Category")

    # Annotate pearson correlation
    corr = np.ma.MaskedArray(data=np.ones_like(ndvi), mask=(ndvi < -999) | (lst < -999))
    ndvi_clean = ndvi[~np.isnan(ndvi) & ~np.isnan(lst)]
    lst_clean = lst[~np.isnan(ndvi) & ~np.isnan(lst)]
    corr = np.corrcoef(ndvi_clean, lst_clean)
    if corr.size >= 4:
        pearson_r = corr[0, 1]
        ax.annotate(f"Pearson r = {pearson_r:.3f}", xy=(0.05, 0.95), ha="left", va="top",
                     fontsize=12, transform=ax.transAxes,
                     bbox=dict(boxstyle="round,pad=0.2", facecolor="white", alpha=0.8))

    out_path = output_dir / "static" / "hexbin_NDVI_vs_LST_split.png"
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  Hexbin plot saved: {out_path}")


# ══════════════════════════════════════════════════════════════════
#  Main
# ══════════════════════════════════════════════════════════════════

def main() -> None:
    parser = argparse.ArgumentParser(description="Generate dense-matrix heatmaps for Helios")
    parser.add_argument("--data-dir", default=DEFAULT_DATA_DIR)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--bbox", nargs=4, type=float, default=DEFAULT_BBOX)
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "static").mkdir(parents=True, exist_ok=True)

    print("Loading dense matrix ...")
    df = load_data(data_dir)
    if df is None or len(df) == 0:
        print("No data found. Exiting.")
        return

    years = years_present(df)
    print(f"Found data for years: {years}")

    print("Generating static heatmaps (per year and decadal)...")
    generate_static_heatmaps(df, output_dir, years)

    print("Generating interactive heatmaps (folium)...")
    generate_interactive_heatmaps(df, output_dir, years)

    print("Generating decadal trend panel ...")
    generate_trend_panel(df, output_dir, years)

    print("Generating NDVI vs LST hexbin ...")
    generate_ndvi_vs_lst_hexbin(df, output_dir)

    print(f"\nDone! Outputs in {output_dir}")
    print(f"WARNING: {WATER_VAPOR_CAVEAT}")


if __name__ == "__main__":
    main()
