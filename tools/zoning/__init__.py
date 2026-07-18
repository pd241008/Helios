# Zoning Tool
# 
# Modular OSM land-use zoning fetch pipeline.
# Each submodule handles one concern:
#
#   config.py     — Category mappings, constants, excluded tags
#   overpass.py   — Overpass API client
#   parser.py     — OSM JSON → GeoJSON conversion
#   geometry.py   — Clipping, sliver detection, deduplication
#   validation.py — Area stats, geographic sanity checks, viz
#   cli.py        — CLI argument parsing and pipeline orchestration
#
# Usage:
#   python -m tools.zoning --bbox "12.8,79.9469,13.23,80.345" --output staging/raw/zoning.geojson
#   python tools/fetch_zoning.py ...   (thin wrapper, backwards-compatible)
