# Helios Analysis — Spatial/Temporal Heatmaps

Run after the ML training/evaluation stage (or independently). Consumes both the
raw per-scene data (GEE track) and the dense Parquet matrix (offline track).

## Caveat

All heatmap titles and outputs are automatically annotated with the water vapor
placeholder warning established in `processing-scala/README.md`. The
LST_split_window values use a constant (2.0 g/cm²) for atmospheric water
vapor, and any numerical outputs should be treated as preliminary.

## Requirements

```bash
uv pip install geemap folium plotly
```

For the GEE track, authenticate with Earth Engine first:
```bash
earthengine authenticate
```

## Track A — GEE heatmaps (scene-level, primary data source)

```bash
uv run python -m analysis.gee_heatmaps
```

Optional arguments:
- `--city-dir` - directory to cache or find data (default: `./data/chennai`)
- `--output-dir` - directory for HTML and PNG outputs (default: `./reports/heatmaps`)
- `--bbox` - four floats: west south east north (default: Chennai AOI)
- `--start-year` / `--end-year` - year range for analysis (default: 2014-2024)

Outputs:
- `reports/heatmaps/gee_interactive_map.html` — toggleable layers per year for B10, B11, ST_B10
- `reports/heatmaps/*.png` — decadal composites

## Track B — Dense-matrix heatmaps (offline, from your already-ingested data)

```bash
uv run python -m analysis.dataset_heatmaps
```

Optional arguments:
- `--data-dir` - path to dense Parquet matrix (default: `../staging/dense`)
- `--output-dir` - directory for outputs (default: `./reports/heatmaps`)
- `--bbox` - four floats (default: Chennai AOI)

Outputs:
- `reports/heatmaps/static/*.png` — per-year and decadal heatmaps for each variable
- `reports/heatmaps/static/trend_panel_LST_split_window.png` — small-multiples decadal trend
- `reports/heatmaps/static/hexbin_NDVI_vs_LST_split.png` — core UHI relationship plot
- `reports/heatmaps/interactive/*.html` — folium interactive heatmaps

## City-agnostic design

Both modules accept `--bbox`, so to run for Bangalore in the next phase:
```bash
uv run python -m analysis.dataset_heatmaps --bbox 77.49 12.84 77.75 13.15
uv run python -m analysis.gee_heatmaps --bbox 77.49 12.84 77.75 13.15
```
