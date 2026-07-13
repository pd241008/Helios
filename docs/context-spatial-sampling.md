# Context: Spatial Sampling for ML Training Pipeline

## Problem

Adjacent 30m Landsat pixels are heavily spatially autocorrelated.
Training XGBoost on every single pixel-row (~91M rows for the Chennai
10-year dense matrix) adds compute cost without proportional signal
gain.  Sampling at the ML training stage reduces compute while keeping
full spatial detail available for Track A/B heatmap analysis.

## Changes made

### Branch `feat/ml-python` (commit `b87c70f`)

**`ml-python/helios_ml/data.py`** — core changes:

- Added `full_resolution=True` default parameter to `load()`.  When
  `False`, spatial sampling is applied; when `True` (the default),
  all rows are returned unchanged.
- Added `--sample-strategy` flag with three options:
  - `none` (default) — no sampling, full data
  - `systematic-grid` — keeps every Nth pixel on a 2-D spatial grid.
    Step `N = round(1/sqrt(rate))`, so rate=0.1 → N=3 → ~1/9 ≈ 11%
    of rows kept.  Uses `rank("dense").over("year")` on lon and lat
    to create a deterministic spatial grid.
  - `stratified-zoning` — samples proportionally within each
    `zoning_category` (or `zoning_target_encoded` if category absent)
    using `rank("ordinal").over("year", strat_col)` to preserve
    class balance.
- Added `--sample-rate` float (0.0–1.0) controlling the target fraction.
- **All sampling operations are lazy** — expressed as Polars window
  functions (`.over()`) on a LazyFrame.  The full dataset is never
  materialised before the final `.collect()`.  Only a COUNT scan
  (`lf.select(pl.len()).collect()`) is run to log the before count.
- Sampling is applied independently within each year partition (via
  `.over("year")`) so temporal coverage is never skewed.
- Before/after row counts and achieved fraction are logged.

**`ml-python/helios_ml/train.py`** — call site changes:

- Added `--sample-strategy` (default `"none"`) and `--sample-rate`
  (default `0.1`) CLI options.
- Changed `load(data_dir)` → `load(data_dir, full_resolution=False,
  sample_strategy=..., sample_rate=...)` — explicitly opts into sampling.

**`ml-python/analysis/dataset_heatmaps.py`** — call site changes:

- Removed duplicate `scan_dense_matrix()` function.
- Imported `load` from `helios_ml.data`.
- `load_data()` now calls `load(data_dir, full_resolution=True)` —
  explicit opt-out, heatmaps always get full resolution.

**`ml-python/tests/test_data.py`** — new test file (15 tests):

- `TestSystematicGridSample` (8 tests): rate boundary cases, step
  math, achieved fractions at 0.1 and 0.25 targets, per-year
  independence, determinism, lazy type check.
- `TestStratifiedZoningSample` (5 tests): rate boundary, category
  proportion preservation (within ±10pp), fallback when no zoning
  column, per-year independence, lazy type check.
- `TestLoadIntegration` (2 tests): full-resolution loads all rows,
  sampling reduces rows to expected count.

### Branch `feat/processing-scala` (commit `1d852c5`)

**`processing-scala/src/main/scala/helios/SpatialJoin.scala`**:

- Added `/*+ BROADCAST(z) */` hint to the spatial join SQL in
  `spatialJoin()`.  This broadcasts the ~50–200 zoning polygons to
  all executors instead of shuffle-joining against ~91M pixel rows.

**`processing-scala/README.md`**:

- Added "Spark local-mode runtime tuning" section covering:
  - Memory: `spark.driver.memory=8g`, `spark.executor.memory=8g`
  - Shuffle partitions: rule of thumb = `2 × physical cores`
  - Broadcast join rationale and the SQL hint
  - Additional recommended Spark flags

## Verification

- 15/15 pytest tests pass (`ml-python/.venv/bin/python -m pytest tests/test_data.py -v`)
- `ruff check` clean on all modified files (pre-existing N806 warnings
  in train.py/split.py for ML-convention `X_train`/`X_test` variables
  are unchanged)
- No data.py / train.py / dataset_heatmaps.py lint errors introduced

## Final row count after sampling

The achieved row count depends on the actual data.  With the
`systematic-grid` strategy at `rate=0.1`:
- Step N = round(1/sqrt(0.1)) = 3
- Each year: keeps ~1/9 of pixels ≈ 11% of rows
- Expected: ~91M → ~10M rows for XGBoost training

With `stratified-zoning` at `rate=0.1`:
- Each (year, zone) group keeps ~10% of rows
- Category proportions are preserved
- Expected: ~91M → ~9M rows
