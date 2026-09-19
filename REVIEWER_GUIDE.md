# Reviewer Guide

Entry point for reviewers. Total fast-verification time: **~10 minutes**.

## What this artifact is

Reproducibility artifact for *"Measurement and Prediction of Land Surface
Temperature in Chennai and Bangalore, India, Using a Polyglot Machine
Learning Pipeline and Landsat 8/9 Imagery"* (Urban Climate submission).

The pipeline has three stages in three languages:

1. **Go** — Landsat 8/9 ingestion from the Planetary Computer STAC API
   (`ingestion-go/`)
2. **Scala/Spark+Sedona** — spatial join, LST math, target encoding
   (`processing-scala/`)
3. **Python** — Polars loading, temporal splits, XGBoost/LightGBM/CatBoost
   ensemble training + SHAP (`ml-python/`)

## 10-minute review path

| Step | Command | Time | Confirms |
|---|---|---|---|
| 1 | `make verify` | < 1 s | shipped checkpoints match SHA-256 manifest (L1) |
| 2 | `cd ml-python && uv sync && uv run pytest -q` | < 1 min | environment resolves; 15/15 tests pass (L2) |
| 3 | open `results/chennai_v2/metrics.json` | — | matches paper Table 2 (R²=0.7999, RMSE=2.50, MAE=1.94) |
| 4 | skim `CLAIM_MAP.md` | 5 min | every paper claim maps to evidence + script |
| 5 | skim `EXPECTED_OUTPUTS.md` | 2 min | reference values + runtimes |

## Going deeper

- **Run one claim end-to-end:** claim C2 via `ml-python/run_dry_run.py`
  (no Spark needed) or full `REPRODUCE.md` stage 3.
- **Trust boundaries:** `REPRODUCIBILITY_LEVELS.md` — what is verified
  (L1/L2) vs bounded (L3/L4).
- **What the artifact does *not* claim:** `LIMITATIONS.md` — especially
  items 4–7 (transcribed tables, lost run JSONs).
- **Methodology changes:** `PROVENANCE.md`; design rationale in
  `docs/adrs/`; incidents in `docs/postmortems/`.

## Claim quick-reference

| Claim | One-liner | Evidence |
|---|---|---|
| C2 | Chennai single-model R²=0.7999 | `results/chennai_v2/metrics.json` |
| C4 | Chennai ensemble: base 0.790, best tuned 0.810 | paper Table 3 (partial archive) |
| C5 | Bangalore ensemble rescues weak models (0.529) | paper Table 5; raw run JSON `results/bangalore/ensemble_metrics.json` |
| C6 | Leak-free per-city split policy | ADR-005, `helios_ml/split.py` |
| C7 | Seasonal encoding dominates SHAP | `results/shap/` |
