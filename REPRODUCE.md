# Reproduction

This guide covers **full reproduction** of the Helios pipeline end-to-end.
For fast verification without re-running experiments, see `VERIFY.md`.

## Prerequisites

- Go 1.22+
- Java 17 + Scala 2.13 (sbt assembly)
- Python 3.12+ with [uv](https://docs.astral.sh/uv/)
- ~700 GB scratch storage (Landsat scenes ≈70 MB; raw parquet ≈2.5–3.0 GB
  per scene before aggregation)
- Network access to the Microsoft Planetary Computer STAC API and
  OpenStreetMap Overpass API

## Environment Setup

```bash
make setup            # go mod download + sbt update + uv sync
```

## Stage 1 — Ingestion (Go)

```bash
make ingest AOI=chennai      # 43 scenes, ~2-3 h (4 workers, PC rate limits)
make ingest-bangalore        # 26 scenes retained after AOI cloud gate
```

Discovery applies a 30% scene cloud gate plus AOI-specific cloud gating
(claim C8). Raw parquet is written to the staging volume (see `Makefile`
for per-AOI paths).

## Stage 2 — Aggregation (Scala/Spark)

```bash
make process AOI=chennai     # ~1-2 h; spatial join + LST math + target encoding
make process AOI=bangalore
```

Output: hive-partitioned dense matrix (`year=YYYY/split=...`), schema in
`docs/data-contracts.md`.

## Stage 3 — ML Training (Python)

```bash
cd ml-python && uv sync

# Chennai (fixed calendar-year 2025-2026 holdout; claim C2)
uv run python -m helios_ml.train --data-dir $CHENNAI_DENSE --reports-dir reports_chennai_v2

# Chennai ensemble (claim C4)
uv run python -m helios_ml.ensemble --data-dir $CHENNAI_DENSE --sample-strategy none --split-strategy marker

# Bangalore ensemble (claim C5)
uv run python -m helios_ml.ensemble --data-dir $BANGALORE_DENSE --sample-strategy none --split-strategy dynamic
```

Full-resolution training runs 21.5M–25.8M rows in float32 with
serialize-after-fit and chunked prediction (ADR-004). Expected wall-clock:
~4–8 h per city on a single workstation (CatBoost ≈28 min/model; see ADR-004
for the memory envelope).

For a no-Spark smoke run of stage 3 (pivot + LST + single XGBoost on a
small slice):

```bash
uv run python run_dry_run.py
```

## Verifying Against Shipped Results

- `results/chennai_v2/metrics.json` must match `results/chennai_v2`
  run output (claim C2).
- Model checkpoints must match `manifest/checkpoint_sha256.txt`
  (`make verify`).

Known reproducibility boundaries are documented in
`REPRODUCIBILITY_LEVELS.md` and `LIMITATIONS.md`.
