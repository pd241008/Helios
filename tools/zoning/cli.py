"""
cli.py — CLI entry point for the zoning fetch pipeline.

Orchestrates: fetch → parse → clip → validate → write.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .overpass import fetch_overpass
from .parser import osm_to_geojson
from .geometry import clip_features_to_bbox
from .validation import print_validation


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Fetch real land-use zoning from OpenStreetMap via Overpass API.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Examples:
  # Chennai (default)
  python -m tools.zoning --bbox "12.8,79.9469,13.23,80.345" \\
      --output staging/raw/zoning.geojson

  # Bangalore
  python -m tools.zoning --bbox "12.84,77.46,13.09,77.75" \\
      --output staging/raw/zoning_blr.geojson --city-label Bangalore
""",
    )
    parser.add_argument(
        "--bbox",
        required=True,
        help="Bounding box: south,west,north,east (WGS84)",
    )
    parser.add_argument(
        "--output",
        required=True,
        help="Output GeoJSON path",
    )
    parser.add_argument(
        "--city-label",
        default="",
        help="City name for logging",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=180,
        help="Overpass API timeout (seconds)",
    )
    parser.add_argument(
        "--skip-validation",
        action="store_true",
        help="Skip geographic sanity checks",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    """Main pipeline: fetch → parse → clip → validate → write."""
    args = parse_args(argv)

    bbox = tuple(float(x.strip()) for x in args.bbox.split(","))
    assert len(bbox) == 4, f"Expected 4 comma-separated values, got {len(bbox)}"
    assert bbox[0] < bbox[2] and bbox[1] < bbox[3], (
        "Invalid bbox: south<west<north<east required"
    )

    city = f" ({args.city_label})" if args.city_label else ""
    print(f"\n═══ fetch_zoning — OSM Land-Use Zoning{city} ═══")
    print(f"  Bbox: {bbox}")

    # 1. Fetch from Overpass
    data = fetch_overpass(bbox, timeout=args.timeout)

    # 2. Convert to GeoJSON
    geojson = osm_to_geojson(data)

    # 3. Clip to bbox and repair invalid geometries
    geojson = clip_features_to_bbox(geojson, bbox)

    # 4. Validate
    if not args.skip_validation:
        print_validation(geojson, bbox)

    # 5. Write output
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(geojson, f, indent=None)  # compact for large files
    print(f"\n  Written: {output_path} ({output_path.stat().st_size / 1e6:.1f} MB)")
    print(f"  Features: {len(geojson['features'])}")
    print(f"\n═══ Done ═══\n")
