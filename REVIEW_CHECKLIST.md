# Review Checklist

Bounded verification checklist. Each item is independently checkable;
expected outcomes in `EXPECTED_OUTPUTS.md`.

## Integrity (≈1 min)

- [ ] `make verify` prints `verify_manifest: PASS (2/2 entries)`
- [ ] `manifest/checkpoint_sha256.txt` lists exactly the two shipped models
      (`models/chennai_v1/lst_model.json`, `models/chennai_v2/lst_model.json`)

## Environment (≈2 min)

- [ ] `cd ml-python && uv sync` resolves the lockfile without errors
- [ ] `uv run pytest -q` reports `15 passed`
- [ ] `cd ingestion-go && go build ./...` succeeds
- [ ] `cd processing-scala && sbt compile` succeeds (optional, ~5 min first run)

## Numbers vs paper (≈3 min)

- [ ] `results/chennai_v2/metrics.json`:
      r2 = 0.7999, rmse = 2.5016, mae = 1.9421 (paper Table 2)
- [ ] `results/chennai_v2/ensemble_metrics_partial.json`:
      XGBoost (Base) r2 = 0.8058, LightGBM (Base) r2 = 0.7538
- [ ] `results/bangalore/ensemble_metrics.transcribed.csv`:
      Tuned Ensemble r2 = 0.529, Base Ensemble r2 = 0.513 (paper Table 5)
- [ ] `results/scene_inventory.md`: 26 scenes Bangalore / 43 Chennai;
      AOI cloud gate < 10% both cities

## Figures (≈2 min)

- [ ] `results/shap/chennai/shap_summary_bar_catboost_base.png` matches
      paper Fig. 5 (doy_cos dominant, zoning sixth)
- [ ] `results/shap/bangalore/shap_summary_bar_xgboost_tuned.png` matches
      paper Fig. 7
- [ ] `results/shap/appendix_zoning_sanity.png` and
      `results/shap/appendix_sliver_defect.png` match appendix figures

## Methodology documents (≈5 min)

- [ ] `CLAIM_MAP.md`: every claim C1–C9 has a script path that exists
- [ ] `REPRODUCIBILITY_LEVELS.md`: L1/L2 marked verified, L3/L4 bounded —
      no overclaiming
- [ ] `LIMITATIONS.md` items 4–7 disclose every table that is transcribed
      rather than shipped as JSON
- [ ] `PROVENANCE.md`: superseded approaches listed match ADRs 001–005

## Optional deeper checks

- [ ] Load `models/chennai_v2/lst_model.json` with `xgb.Booster()` (VERIFY.md step 4)
- [ ] Run claim C2 via `ml-python/run_dry_run.py` on a regenerated dataset
- [ ] Attempt full `REPRODUCE.md` (1–2 days) — see `REPRODUCIBILITY_LEVELS.md` L4 bounds
