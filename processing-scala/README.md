# Helios — Phase 2: Scala/Spark Aggregation Layer

Consumes the raw long-format Parquet files produced by `ingestion-go` under
`staging/raw/landsat/` (columns: `tile_id`, `band`, `value`, `timestamp`,
`lulc_class`), performs a Sedona `ST_Contains` spatial join against zoning
polygons from `staging/raw/lulc/zoning.geojson`, computes split-window Land
Surface Temperature (LST) from the Landsat thermal bands, target-encodes
the high-cardinality `zoning_category` column, and writes a dense ZSTD-compressed
Parquet feature matrix partitioned by `year`/`split` to `staging/dense/`.

## Source files

| File | Responsibility | Key config knobs |
|------|----------------|------------------|
| `SpatialJoin.scala` | Pivots the long-format band/value pairs into wide pixels (one row per lat/lon), loads the zoning GeoJSON, and runs a Sedona point-in-polygon join. | `zoning-path` (GeoJSON path), `lulc-category-col` (zoning attribute name in the GeoJSON features). |
| `LSTMath.scala` | Computes the full NDVI → Pv → emissivity → BT → split-window LST cascade. Retains `ST_B10` (single-channel) as a baseline column. | `emis-soil-10`, `emis-veg-10`, `emis-soil-11`, `emis-veg-11` (emissivity constants); `sw-a0` … `sw-a6` (split-window coefficients); `water-vapor` (atmospheric water vapour placeholder); `ndvi-soil`, `ndvi-veg` (NDVI thresholds). |
| `TargetEncoder.scala` | Bayesian-smoothed target encoding of categorical columns against the LST target. Provides both a global-smoothing mode and a K‑fold mode to prevent target leakage. | `target-smoothing` (Bayesian prior strength), `k` (number of folds in `encodeFolded`). |
| `FeatureMatrix.scala` | Selects the final column set, rounds floats to 4 decimal places, assigns a `train`/`test` split marker based on acquisition year, drops rows with null lat/lon/LST, and writes ZSTD Parquet partitioned by `year`/`split`. | `train-year-start`/`end`, `test-year-start`/`end`. |

## Known limitations

- **Atmospheric water vapour placeholder.** The split-window equation in
  `LSTMath.scala` uses a constant `water-vapor` (~2.0 g/cm²) supplied via
  config rather than a per-scene value derived from a real atmospheric product.
  This introduces systematic error into the `LST_split_window` column.
  **TODO** — wire in a real water vapour data source (MODIS MOD07, NCEP
  reanalysis, or ERA5) keyed by scene `acquisition_date` and geographic
  location before trusting split-window output for anything beyond prototyping.

- **Split-window fallback.** When a `B11_TIR` band is absent for a given tile,
  `LSTMath` falls back to the single-channel `ST_B10` (atmospherically
  corrected L2) or to `BT10` (uncorrected brightness temperature). The current
  test fixture from `generate-test-data` omits `B11_TIR` entirely, so the
  fallback path is exercised in all test runs. It is not yet confirmed whether
  real ingested scenes from the Phase 1.1 STAC fetcher will always carry
  `B11_TIR` — check the fetcher's band asset mapping before assuming
  split-window output will be available in production.

## How to run

```bash
# Generate test data (Go) — only needed if staging/raw/ is empty
cd ingestion-go && go run ./cmd/generate-test-data && cd ..

# Run the Scala/Spark pipeline (points to staging/raw/ by default)
cd processing-scala && sbt "runMain helios.Main"

# Or via the project Makefile
make process
```

Expected output: ZSTD-compressed Parquet files under `staging/dense/`,
partitioned as `year=<YYYY>/split=<train|test>/`. The pipeline can be
configured via `--key value` arguments on the `runMain` command line (see
`Config.scala` for the full list of overridable parameters).
