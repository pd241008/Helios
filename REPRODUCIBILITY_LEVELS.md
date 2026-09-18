# Reproducibility Levels

What "reproducible" means at each level of this artifact, and which
guarantees hold where.

| Level | Guarantee | Effort | Status |
|---|---|---|---|
| **L1 — Integrity** | Shipped files match SHA-256 manifests | `make verify` (< 1 s) | ✅ verified |
| **L2 — Environment** | Locked dependency set installs and unit tests pass | `uv sync && pytest` (< 5 min) | ✅ verified (15/15) |
| **L3 — Checkpoint-level** | Shipped checkpoints load and produce the shipped/paper metrics, given a regenerated dense matrix | dataset regen + `helios_ml.train` | 🟡 requires dataset regeneration |
| **L4 — Full pipeline** | Raw STAC queries → dense matrices → shipped metrics | `REPRODUCE.md`, ~1–2 days | 🟡 bounded (see drift note) |

## Drift bounds (L3/L4)

- **Deterministic given data.** Given identical dense matrices, training is
  deterministic for fixed seed 42 (no GPU nondeterminism — all runs are
  CPU float32; XGBoost `hist`, LightGBM, CatBoost, HistGB).
- **Ingestion drift.** Planetary Computer scene availability and asset
  signatures can change; scene *sets* should be stable for fixed
  space/"time queries (Landsat archive is immutable) but download URLs and
  pagination details may drift.
- **OSM drift.** Zoning polygons are living data; the zoning layer used
  for the paper (2026-08) will not re-fetch identically. Zoning coverage
  percentages may shift by small amounts.
- **Numeric tolerance.** Regenerated-data runs should reproduce paper
  metrics within ±0.01 R² / ±0.05 K RMSE; larger deviations indicate a
  dataset or split-policy mismatch (check ADR-005 first).

## Not claimed

- Bitwise-identical re-ingestion of raw data (L4 is bounded, not exact).
- Multi-seed variance bands (single seed 42; see `LIMITATIONS.md`).
