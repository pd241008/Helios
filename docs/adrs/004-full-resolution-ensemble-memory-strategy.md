# ADR 004: Memory-Safe Full-Resolution Ensemble Strategy

## Status
Accepted (2026-08-21)

## Context
The multi-model ensemble pipeline (`helios_ml/ensemble.py`: XGBoost, LightGBM,
CatBoost, HistGradientBoosting) OOM-killed twice when training on the
full-resolution dense matrices (~19--26M rows) on an 11 GB RAM host:

1. **Run 1** — killed during CatBoost `fit()` at ~10.0 GB RSS.
2. **Run 2** — after adding float32 conversion and `used_ram_limit='4gb'`,
   CatBoost trained all 1000 iterations successfully (~28 min), but the
   process was killed at **8.7 GB RSS during the downstream predict/SHAP
   phase**, losing the entire training run because nothing had been written
   to disk.

Root causes beyond CatBoost itself:

- Polars DataFrames (`full_df`, `feature_df`, float64) stayed referenced in
  scope for the whole run even after numpy conversion.
- Every fitted model was retained in memory simultaneously
  (`fitted_base`/`fitted_tuned` dicts) to support ensemble averaging.
- `.predict(X_test)` allocated output over millions of rows in one call.
- Any crash after `fit()` destroyed completed work (no serialization).

## Decision

Six changes to `helios_ml/ensemble.py` / `evaluate.py`:

1. **float32 ingestion** — convert feature/target matrices once via
   `to_numpy().astype(np.float32)`; halves tree-library ingestion footprint.
2. **CatBoost budget** — `used_ram_limit='4gb'` on both Base and Tuned configs.
3. **Serialize immediately after fit()** — every model is dumped to
   `<reports>/models/<name>.joblib` *before* predict/eval/SHAP runs. A
   downstream crash can only cost seconds, never a trained model. Resume
   logic reloads serialized models instead of refitting.
4. **Chunked prediction** — `predict_in_chunks()` predicts in 1M-row blocks
   into a preallocated float32 array instead of one array-wide call.
5. **Prediction-vector ensembles** — the mean ensemble averages cached
   per-model test-prediction vectors rather than live fitted models, so no
   more than one model is resident at any time.
6. **Eager frees** — float64 polars frames are `del`-ed (+ `gc.collect()`)
   right after float32 conversion.

SHAP is bounded to a random sample of **n = 10,000 test rows**
(`SHAP_MAX_ROWS`, fixed seed), recorded per model as `shap_sample_rows`
in `ensemble_metrics.json`. This is an interpretation-only subsample: it does
not affect what models are trained or evaluated on, and is disclosed in the
methods text.

## Consequences
**Positive:**
- Full-resolution 4-model ensembles (CatBoost included) fit on both cities;
  peak RSS ≤ 6.6 GB versus the 8.7 GB crash point.
- Completed runs are crash-proof: every model checkpointed to disk the moment
  it finishes fitting.
- Results are reproducible from serialized models without retraining.

**Negative:**
- `used_ram_limit` makes CatBoost spill/recompute internally; training is
  slower than unconstrained fits.
- Model artifacts add ~500 MB/joblib set per city on the reports volume.
