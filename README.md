# Helios — Land Surface Temperature Prediction Pipeline

A polyglot monorepo for a geospatial Machine Learning pipeline that predicts
**Land Surface Temperature (LST)** from Landsat GeoTIFF imagery, OpenStreetMap
spatial shards, and high-cardinality land-use/land-cover (LULC) features.

## Architecture

```
┌─────────────────┐      .parquet       ┌──────────────────────┐      .parquet       ┌──────────────────┐
│  Go  (Ingest)   │ ──────────────────► │  Scala  (Aggregate)  │ ──────────────────► │ Python (ML/Train)│
│  goroutine pool │   staging/raw/      │  Spark transforms    │   staging/dense/    │ XGBoost / Polars │
└─────────────────┘                     └──────────────────────┘                     └──────────────────┘
```

| Layer | Language | Tooling | Responsibility |
|---|---|---|---|
| **Ingestion** | Go 1.22+ | `go mod` | Concurrent Landsat/OSM fetch → raw `.parquet` |
| **Processing** | Scala 2.13 / Spark 3.5 | `sbt` | Spatial joins, target encoding → dense `.parquet` |
| **ML Training** | Python 3.12+ | `uv` | Model training (XGBoost / RF) with Polars |

## Quick Start

```bash
# Prerequisites: go 1.22+, java 17+, sbt 1.10+, python 3.12+, uv
make setup     # Install all deps across languages
make ingest    # Run Go ingestion worker pool
make process   # Run Scala/Spark aggregation
make train     # Run Python ML training
make all       # Full pipeline end-to-end
```

## Directory Layout

```
Helios/
├── Makefile                  # Cross-language orchestrator
├── ingestion-go/             # Go concurrent ingestion engine
│   ├── go.mod
│   ├── go.sum
│   ├── cmd/ingest/main.go
│   └── internal/
│       ├── fetcher/fetcher.go
│       ├── parser/parser.go
│       └── worker/pool.go
├── processing-scala/         # Scala/Spark aggregation layer
│   ├── build.sbt
│   ├── project/build.properties
│   └── src/main/scala/helios/
│       ├── Main.scala
│       ├── SpatialJoin.scala
│       └── TargetEncoder.scala
├── ml-python/                # Python ML training pipeline
│   ├── pyproject.toml
│   └── helios_ml/
│       ├── __init__.py
│       ├── train.py
│       ├── data_loader.py
│       └── evaluate.py
└── staging/                  # Local data staging (git-ignored)
    ├── raw/
    └── dense/
```

## License

Internal / Proprietary — see project governance.
