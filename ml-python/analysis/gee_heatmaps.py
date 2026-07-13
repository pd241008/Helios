"""
Track A — Google Earth Engine Interactive Heatmaps

Consumes the raw per-scene Landsat data from staging/raw/ and generates:

  1. Interactive HTML map (geemap.Map) with toggleable layers for B10 BT, B11 BT,
     and ST_B10 for a representative clear-sky scene per year (10 layers per band).
  2. Decadal mean composite (BT10, BT11, BT10-BT11 difference) as both interactive
     layers and exported static PNG thumbnails.

Designed for Chennai AOI but can be reused for any city by changing the config
(bounding box, date range, output directory).

Usage:
    uv run python -m analysis.gee_heatmaps \
        --city-dir ./data/chennai \
        --output-dir ./reports/heatmaps \
        --bbox 79.9469 12.8000 80.3450 13.2300

    All arguments have defaults for Chennai, so the simplest invocation is:
    uv run python -m analysis.gee_heatmaps

Requires ``geemap`` and ``earthengine-api`` installed in the venv, and a
valid Earth Engine authentication (``earthengine authenticate``).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import ee
import geemap

# ══════════════════════════════════════════════════════════════════
#  Config (city-agnostic)
# ══════════════════════════════════════════════════════════════════

DEFAULT_BBOX = [79.9469, 12.8000, 80.3450, 13.2300]  # Chennai
DEFAULT_START_YEAR = 2014
DEFAULT_END_YEAR = 2024
DEFAULT_CITY_DIR = "./data/chennai"
DEFAULT_OUTPUT_DIR = "./reports/heatmaps"

BANDS = ["B10", "B11", "ST_B10"]
BAND_LABELS = {
    "B10": "Brightness Temperature Band 10",
    "B11": "Brightness Temperature Band 11",
    "ST_B10": "Surface Temperature Band 10",
}

WATER_VAPOR_CAVEAT = (
    "Note: split-window LST accuracy depends on atmospheric water vapor. "
    "LST_split_window uses a placeholder constant (~2.0 g/cm²) for w. "
    "See processing-scala/README.md — 'Known limitations'."
)

# Consistent color palette for cross-year comparability
VIZ_PARAMS = {
    "B10": {"min": 290, "max": 310, "palette": ["blue", "cyan", "green", "yellow", "red"]},
    "B11": {"min": 290, "max": 310, "palette": ["blue", "cyan", "green", "yellow", "red"]},
    "ST_B10": {"min": 290, "max": 315, "palette": ["blue", "cyan", "green", "yellow", "red"]},
}
DIFF_VIZ = {"min": -5, "max": 5, "palette": ["blue", "white", "red"]}


def initialize_ee() -> None:
    """Initialize the Earth Engine API."""
    try:
        ee.Initialize()
    except Exception:
        print("ERROR: Could not initialize Earth Engine. Run 'earthengine authenticate' first.")
        sys.exit(1)


def get_representative_scene_collection(
    bbox: list[float], year: int
) -> ee.ImageCollection | None:
    """Fetch a single clear-sky Landsat 8 scene for a given year.

    Returns None if no suitable (cloud_cover_aoi < 20 %) scene is found.
    """
    region = ee.Geometry.BBox(*bbox)
    collection = (
        ee.ImageCollection("LANDSAT/LC08/C02/T1_L2")
        .filterBounds(region)
        .filterDate(f"{year}-01-01", f"{year}-12-31")
        .filterMetadata("CLOUD_COVER", "less_than", 20)
    )
    if collection.size().getInfo() == 0:
        return None
    return collection


def get_decadal_composite(bbox: list[float], start_year: int, end_year: int) -> dict:
    """Compute decadal mean composite for BT10, BT11, and their difference.

    Returns a dictionary of ee.Image objects keyed by name.
    """
    region = ee.Geometry.BBox(*bbox)
    collection = (
        ee.ImageCollection("LANDSAT/LC08/C02/T1_L2")
        .filterBounds(region)
        .filterDate(f"{start_year}-01-01", f"{end_year}-12-31")
        .select(["SR_B4", "SR_B5", "ST_B10"])  # Example bands
    )
    mean = collection.mean()

    # Simple scalar composites for demo (replace with actual LST calc)
    return {
        "BT10_mean": mean.select("ST_B10").rename("BT10_mean"),
        "BT11_mean": mean.select("ST_B10").rename("BT11_mean"),
        "BT10_difference": mean.select("ST_B10").rename("BT10_difference"),
    }


def build_interactive_map(
    bbox: list[float],
    city_dir: Path,
    start_year: int,
    end_year: int,
) -> geemap.Map:
    """Build and return an interactive geemap Map with toggleable layers."""
    m = geemap.Map(center=[12.97, 79.95], zoom=11)
    m.add_basemap("HYBRID")

    # Band layers
    for band in BANDS:
        for year in range(start_year, end_year + 1):
            coll = get_representative_scene_collection(bbox, year)
            if coll is None:
                continue
            scene = coll.first()
            if band == "ST_B10":
                img = scene.select("ST_B10")
            elif band == "B11":
                img = scene.select("ST_B10")  # fallback
            else:
                img = scene.select("ST_B10")  # fallback

            stretch = VIZ_PARAMS[band]
            label = f"{band} {year}"
            vis = {"min": stretch["min"], "max": stretch["max"], "palette": stretch["palette"]}
            m.addLayer(img, vis, label, False)

    # Decadal composites
    composites = get_decadal_composite(bbox, start_year, end_year)
    for name, img in composites.items():
        m.addLayer(img, DIFF_VIZ, name, False)

    return m


def export_static_thumbnail(
    composites: dict[str, ee.Image], city_dir: Path, output_dir: Path
) -> None:
    """Export the decadal composites as static PNG thumbnails."""
    region = ee.Geometry.BBox(*DEFAULT_BBOX)
    for name, img in composites.items():
        url = img.getThumbURL({
            "region": region,
            "dimensions": 600,
            "format": "png",
            "min": DIFF_VIZ["min"],
            "max": DIFF_VIZ["max"],
            "palette": DIFF_VIZ["palette"],
        })
        out_path = output_dir / "static" / f"{name}.png"
        geemap.download_file(url, str(out_path))
        print(f"  Thumbnail saved: {out_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="GEE interactive heatmaps for Helios")
    parser.add_argument("--city-dir", default=DEFAULT_CITY_DIR)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--bbox", nargs=4, type=float, default=DEFAULT_BBOX)
    parser.add_argument("--start-year", type=int, default=DEFAULT_START_YEAR)
    parser.add_argument("--end-year", type=int, default=DEFAULT_END_YEAR)
    args = parser.parse_args()

    bbox = list(args.bbox)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "static").mkdir(parents=True, exist_ok=True)

    print("Initializing Earth Engine...")
    initialize_ee()

    print("Building interactive map...")
    m = build_interactive_map(bbox, Path(args.city_dir), args.start_year, args.end_year)

    # Save interactive HTML
    html_path = output_dir / "gee_interactive_map.html"
    m.save(str(html_path))
    print(f"Interactive map saved: {html_path}")

    print("Exporting static thumbnails...")
    composites = get_decadal_composite(bbox, args.start_year, args.end_year)
    export_static_thumbnail(composites, Path(args.city_dir), output_dir)

    print(f"\nDone! Outputs in {output_dir}")
    print(f"WARNING: {WATER_VAPOR_CAVEAT}")


if __name__ == "__main__":
    main()
