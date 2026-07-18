#!/usr/bin/env python3
"""
fetch_zoning.py — Backwards-compatible wrapper.

The actual implementation has been modularized into tools/zoning/:

    tools/zoning/
    ├── __init__.py      — Package docstring
    ├── __main__.py      — python -m tools.zoning entry point
    ├── cli.py           — CLI argument parsing + pipeline orchestration
    ├── config.py        — Category mappings, constants, excluded tags
    ├── geometry.py      — Bbox clipping, sliver detection, deduplication
    ├── overpass.py      — Overpass API client
    ├── parser.py        — OSM JSON → GeoJSON conversion
    └── validation.py    — Area stats, sanity checks, PNG visualization

Usage (unchanged):
    python tools/fetch_zoning.py \\
        --bbox "12.8,79.9469,13.23,80.345" \\
        --output staging/raw/zoning.geojson \\
        --city-label Chennai
"""

from zoning.cli import main

if __name__ == "__main__":
    main()
