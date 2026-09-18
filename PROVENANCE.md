# Provenance

Methodological history: what changed, when, and why. Superseded approaches
are documented rather than deleted, so reviewers can trace the paper's
numbers to the methodology that produced them.

## Methodology timeline (2026-07 → 2026-09)

| Date | Event | Record |
|---|---|---|
| 2026-07 | Initial ingestion pipeline (Go), 60-scene Chennai v1 at 30% cloud gate | `docs/phase1-ingestion.md` |
| 2026-07-20 | Target-leakage guard introduced — thermal precursors stripped from features | ADR-001 |
| 2026-07-20 | STAC pagination limit enforcement after runaway discovery | ADR-002, postmortem 2026-08-18 |
| 2026-08 | Chennai v2 re-ingestion: 43 scenes at `eo:cloud_cover < 10%` + AOI gate | `docs/context-dual-city-datasets.md` |
| 2026-08-18 | Autonomous ingestion chaining incident | postmortem 2026-08-18 |
| 2026-08-19 | Single-model runs (18-scene v1); unlabeled negative-R² run retained in `results/archive/` | ADR-005 (split policy) |
| 2026-08-19 | SHAP silent-failure logging added after missing output | ADR-003 |
| 2026-08-21 | Ensemble OOM at predict/SHAP on full resolution — memory strategy redesigned | postmortem 2026-08-21, ADR-004 |
| 2026-08 | Full-resolution ensemble shipped: serialize-after-fit, chunked predict, float32 | ADR-004 |
| 2026-08 | Temporal split policy finalized: per-city (dynamic vs marker) | ADR-005 |
| 2026-09 | DuckDB-based independent corroboration of Chennai (R²=0.7440) | `ml-python/run_dry_run.py` (paper §Results) |
| 2026-09 | Paper v12 (Urban Climate submission) — numbers frozen | `results/` + `EXPECTED_OUTPUTS.md` |

## Superseded approaches

| Superseded | By | Why |
|---|---|---|
| 60-scene Chennai v1 (30% gate) | 43-scene v2 (10% gate) | cleaner cloud profile; v1 flagged do-not-use |
| 18-scene / 10% sample table in early drafts | full-resolution runs | sampling bias; see `docs/context-spatial-sampling.md` |
| Static year-range split (2016–2024 train / 2025–2026 test as fallback) | per-city policy (ADR-005) | fallback triggered silently on missing markers; dynamic window is leak-free by construction |
| Year-based `_split_by_year` fallback | `_split_by_last_12_months` | same |
| `VotingRegressor` ensemble | equal-weight mean of cached prediction vectors | memory: predict-chunking + serialize-after-fit (ADR-004) |
| Single global bbox hardcoded in `SpatialJoin.scala` | `spark.helios.bbox.*` conf | dual-city support |
| Global `drop_nulls()` in dataset heatmaps | per-variable null filtering | thermal-sparse rows need not kill all variables |

## Archived-but-unlabeled result

`results/archive/metrics_unlabeled_2026-08-19_run.json` (R² = −0.31) is kept
deliberately: it documents the failure mode (stale calendar-year markers on a
dynamic-window dataset) that motivated ADR-005. Do not cite it.
