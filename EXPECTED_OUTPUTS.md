# Expected Outputs

What to expect when running each verification / reproduction step.
Use this to confirm your environment is configured correctly.

## Checkpoint verification

```bash
make verify
```

**Runtime:** < 1 s

**Expected output:**
```
verify_manifest: PASS (2/2 entries)
```

## Python test suite

```bash
cd ml-python && uv sync && uv run pytest -q
```

**Runtime:** < 5 s (no dataset required)

**Expected output:**
```
15 passed
```

## Shipped-metric reference values (claims C2, C4, C5)

These are the values the shipped checkpoints and paper tables carry.
A faithful re-run on a regenerated dataset should land within the
tolerances in `REPRODUCIBILITY_LEVELS.md` (L3).

### Chennai v2 — single XGBoost (fixed 2025–2026 holdout)

| Metric | Value |
|---|---|
| MAE | 1.9421 K |
| RMSE | 2.5016 K |
| R² | 0.7999 |
| MAPE | 0.6196 % |

Source: `results/chennai_v2/metrics.json` (paper Table 2).
Train/test: 19.3M / 6.54M rows, 43 scenes.

### Chennai v2 — ensemble (same split)

Key rows (paper Table 3; full table transcribed in
`results/chennai_v2/ensemble_metrics.transcribed.csv`):

| Model | MAE (K) | RMSE (K) | R² |
|---|---|---|---|
| XGBoost (Base) | 1.903 | 2.465 | 0.806 |
| CatBoost (Lit.-standard config) | 1.895 | 2.438 | 0.810 |
| Base Ensemble | 1.972 | 2.565 | 0.790 |
| Lit.-standard Ensemble | 2.105 | 2.733 | 0.761 |

### Bangalore — ensemble (rolling 12-month holdout, cutoff 2024-12-10)

| Model | R² | RMSE (K) |
|---|---|---|
| XGBoost (single, primary) | 0.292 | 2.50 |
| Base Ensemble | 0.513 | 2.077 |
| **Tuned Ensemble** | **0.529** | **2.041** |

Source: transcribed in `results/bangalore/ensemble_metrics.transcribed.csv`
(paper Table 5). Train/test: 18.2M / 3.27M rows, 26 scenes.

## Full reproduction runtimes (reference workstation, single machine)

| Stage | Command | Runtime |
|---|---|---|
| Setup | `make setup` | 5–15 min (sbt cache dominated) |
| Ingestion | `make ingest AOI=chennai` | ~2–3 h (43 scenes, 4 workers) |
| Aggregation | `make process AOI=chennai` | ~1–2 h (Spark local, 6 GB) |
| Single-model training | `helios_ml.train` | ~30–60 min (25.8M rows) |
| Ensemble (8 models + 2 ensembles) | `helios_ml.ensemble` | ~4–8 h per city (CatBoost ≈28 min/model; ADR-004) |
| Dry-run smoke (no Spark) | `run_dry_run.py` | minutes (small slice) |

SHAP figures are generated per model during the ensemble run with a
bounded n=10,000-row test sample (fixed seed 42).
