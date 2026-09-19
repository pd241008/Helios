# Scientific Claim Map

Stable identifiers for every scientific claim in the Helios artifact. Each
entry links a paper claim to its evidence, generating script, and output file.
Claim numbering mirrors the paper (Urban Climate submission, v12).

| ID | Paper Claim | Manifest | Evidence | Script | Output |
|---|---|---|---|---|---|
| C1 | A polyglot pipeline (Go ingestion → Spark/Sedona aggregation → Python ML) measures and predicts LST from Landsat 8/9 for two Indian metros | `experiment_manifests/C1-pipeline.json` | End-to-end run over 69 scenes (26 Bangalore, 43 Chennai) producing 21.5M/25.8M-row dense matrices | `Makefile` targets `ingest`/`process`/`train` (stages 1–3) | `results/chennai_v2/metrics.json`, `results/bangalore/` (see limitations) |
| C2 | Chennai single-model: 25.8M rows, genuine 2025–2026 holdout, R²=0.7999 (RMSE=2.50 K, MAE=1.94 K) | `experiment_manifests/C2-chennai-single.json` | Primary XGBoost run metrics | `ml-python/helios_ml/train.py` | `results/chennai_v2/metrics.json` |
| C3 | Independent DuckDB-based pipeline corroborates Chennai at R²=0.7440 (RMSE=2.83 K) | `experiment_manifests/C3-duckdb-corroboration.json` | Corroboration run metrics | `ml-python/run_dry_run.py` | recorded in paper §Results; per-run JSON not persisted (see `results/README.md`) |
| C4 | Chennai ensemble: base ensemble R²=0.790; literature-standard CatBoost (Base) is the best tuned model at R²=0.810; ensembling does not beat the already-strong single model | `experiment_manifests/C4-chennai-ensemble.json` | 8-model + 2-ensemble evaluation on identical split | `ml-python/helios_ml/ensemble.py --split-strategy marker` | paper Table 3; raw run output in `results/chennai_v2/ensemble_metrics.json` (partial archive retained for provenance) |
| C5 | Bangalore: individual models are unstable under the thin seasonally-narrow test window (R²=0.27–0.36), but the four-model ensemble recovers R²=0.529 (tuned) / 0.513 (base) | `experiment_manifests/C5-bangalore-ensemble.json` | 8-model + 2-ensemble evaluation, rolling 12-month holdout | `ml-python/helios_ml/ensemble.py --split-strategy dynamic` | paper Table 5; raw run output in `results/bangalore/ensemble_metrics.json` (recovered 2026-09-19) |
| C6 | Temporal splits are leak-free: per-city policy (ADR-005) — dynamic rolling 12-month window (Bangalore), fixed calendar-year markers (Chennai) | `experiment_manifests/C6-split-policy.json` | Split implementation + boundary derivation from year+doy | `ml-python/helios_ml/split.py` | ADR-005; cutoff dates in `EXPECTED_OUTPUTS.md` |
| C7 | SHAP attribution: seasonal encoding dominates (doy_cos/doy_sin), zoning category ranks sixth (Chennai); ensembling recovers zoning/NDVI signal (Bangalore) | `experiment_manifests/C7-shap.json` | Bounded-sample SHAP (n=10,000 test rows, fixed seed) | `ml-python/helios_ml/evaluate.py` | `results/shap/*.png`; paper Figs. 5–8 |
| C8 | AOI-specific cloud gating retains 26/255 (Bangalore) and 43 (Chennai) scenes while enforcing ≤30% cloud | `experiment_manifests/C8-cloud-gating.json` | Per-scene AOI cloud scans of QA_PIXEL rasters | `ingestion-go/cmd/check_all_aoi_cloud`, `cmd/only_qa` | `docs/context-dual-city-datasets.md`; scene inventory in `results/scene_inventory.md` |
| C9 | Zoning scope is explicit: spatial inner join restricts data to municipal-zoning-covered pixels (26.7% Chennai, 34.52% Bangalore) — a stated boundary, not a hidden filter | `experiment_manifests/C9-zoning-scope.json` | Join coverage metrics + zoning sanity checks | `processing-scala/src/main/scala/helios/SpatialJoin.scala` | paper §Zoning data validation; `docs/context-spatial-sampling.md` |

## Claim Dependencies

```
C1 (pipeline end-to-end)
    ├── C2 (Chennai single-model headline)
    │     └── C3 (independent corroboration)
    │     └── C4 (Chennai ensemble: tests whether ensembling helps a strong model)
    ├── C5 (Bangalore ensemble: tests whether ensembling rescues weak models)
    ├── C6 (leak-free splits — precondition for C2/C4/C5)
    ├── C7 (SHAP attribution — interpretation layer for C2/C4/C5)
    ├── C8 (cloud gating — scene acquisition precondition for C1)
    └── C9 (zoning scope — domain boundary for all trained models)
```

## Cross-References

- **Architecture**: `docs/architecture.md`
- **Data contracts**: `docs/data-contracts.md`
- **ADRs**: `docs/adrs/` (001–005)
- **Postmortems**: `docs/postmortems/`
- **Provenance**: `PROVENANCE.md`
- **Limitations**: `LIMITATIONS.md`
- **Reproduction**: `REPRODUCE.md` · **Fast verification**: `VERIFY.md`
