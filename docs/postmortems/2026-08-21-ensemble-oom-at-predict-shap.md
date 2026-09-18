# Postmortem: Ensemble OOM Losses at Predict/SHAP Stage

**Date:** 2026-08-21
**Status:** Resolved

## Incident Summary
Three consecutive full-resolution ensemble runs were lost before any results
were persisted. The first two died by kernel OOM-killer; the third was killed
by an agent shell-session timeout that tore down its children. In all three
cases models had already trained successfully (CatBoost completed all 1000
iterations, RMSE 5.11 → 1.43 in run 2) but **nothing was serialized**, so the
completed work was destroyed by failures in downstream steps.

## Root Cause
1. **No checkpoint between `fit()` and reporting.** Model serialization,
   metric writing, and SHAP all happened after prediction; a crash anywhere in
   that tail discarded the training compute (~30 min/model).
2. **Memory accumulation across the run.** Float64 polars frames stayed in
   scope; all fitted models were retained simultaneously for ensemble
   averaging; single-call `.predict()` over 1.6--6.5M test rows spiked
   allocation. Combined peak exceeded the 11 GB host during CatBoost's
   predict/SHAP phase (8.7 GB RSS at kill).
3. **Unsafe backgrounding.** A `nohup ... &` job launched from a tool session
   was process-group-killed when that session hit its command timeout —
   `nohup` only ignores SIGHUP.

## Timeline
- **07:38** — Run A OOM-killed during CatBoost fit (10.0 GB RSS).
- **07:40** — float32 + `used_ram_limit='4gb'` patch applied (CatBoost-side fix only).
- **08:12** — Run B: CatBoost Base finishes 1000 iterations.
- **08:14** — Run B OOM-killed at predict/SHAP (8.7 GB RSS); no metrics written.
- **10:33** — Run C relaunched with full fix set but backgrounded unsafely.
- **10:39** — Run C killed by tool-session teardown (log frozen mid-XGBoost).
- **10:41** — Run D relaunched via `setsid` (own process group). Completed all
  8 models + both ensembles with zero kills; peak RSS 6.6 GB.

## Action Items
1. **[DONE]** Serialize every model to `<reports>/models/<name>.joblib`
   immediately after `fit()`, before predict/eval/SHAP (ADR-004).
2. **[DONE]** Chunked prediction (`predict_in_chunks`, 1M rows/call).
3. **[DONE]** Ensembles average cached prediction vectors, not live models;
   float64 frames freed after conversion (ADR-004).
4. **[DONE]** SHAP bounded to n=10,000 sampled test rows, fixed seed,
   disclosed per model as `shap_sample_rows` (was already bounded; now
   recorded).
5. **[DONE]** Long-running jobs launched with `setsid ... < /dev/null &` and
   verified detached (PPID ≠ session shell) before ending the session.
