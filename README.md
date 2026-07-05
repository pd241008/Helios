# 🔥 Helios — Land Surface Temperature Prediction Pipeline

[![Go](https://img.shields.io/badge/Go-00ADD8?style=for-the-badge&logo=go&logoColor=white)](https://go.dev/)
[![Scala](https://img.shields.io/badge/Scala-DC322F?style=for-the-badge&logo=scala&logoColor=white)](https://www.scala-lang.org/)
[![Spark](https://img.shields.io/badge/Spark-E25A1C?style=for-the-badge&logo=apache-spark&logoColor=white)](https://spark.apache.org/)
[![Python](https://img.shields.io/badge/Python-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![XGBoost](https://img.shields.io/badge/XGBoost-FF6600?style=for-the-badge&logo=xgboost&logoColor=white)](https://xgboost.readthedocs.io/)

A polyglot geospatial ML pipeline that predicts **Land Surface Temperature (LST)** for Chennai, India, by fusing Landsat 8 satellite imagery with high-cardinality land-use/land-cover (LULC) zoning data.

---

## 🏗️ Architecture

```mermaid
flowchart LR
    A["🌍 Landsat 8<br/>STAC API"] -->|HTTP| B["Go Ingestion<br/>Worker Pool"]
    B -->|raw .parquet| C["staging/raw/"]
    C --> D["Scala/Spark<br/>Aggregation"]
    D -->|dense .parquet| E["staging/dense/"]
    E --> F["Python/XGBoost<br/>ML Training"]
    F --> G["📈 LST Model"]
```

```mermaid
flowchart TD
    subgraph "Phase 1 — Go"
        A1[Landsat Fetcher] --> A2[Vector Parser]
        A2 --> A3[Raw Parquet Export]
    end
    subgraph "Phase 2 — Scala"
        B1[Spatial Alignment] --> B2[Math Pipeline<br/>NDVI → Pv → ε → LST]
        B2 --> B3[Target Encoding]
        B3 --> B4[Dense Feature Matrix]
    end
    subgraph "Phase 3 — Python"
        C1[Polars Load] --> C2[Temporal Split]
        C2 --> C3[XGBoost Training]
        C3 --> C4[SHAP Evaluation]
    end
    A3 --> B1
    B4 --> C1
```

| Layer | Language | Tooling | Responsibility |
|-------|----------|---------|----------------|
| **Ingestion** | Go 1.22+ | `go mod` | Concurrent Landsat/OSM fetch → raw `.parquet` |
| **Processing** | Scala 2.13 / Spark 3.5 | `sbt` | Spatial joins, target encoding → dense `.parquet` |
| **ML Training** | Python 3.12+ | `uv` + Polars | XGBoost training & SHAP evaluation |

---

## 🧠 The Stack: Why Polyglot?

### Go (Ingestion Gateway)
Selected for its **concurrency primitives** — goroutines and channels make it trivial to run a bounded worker pool of 8+ concurrent downloads with graceful cancellation. The standard library's `net/http` is sufficient for REST API calls, and pure-Go Parquet libraries avoid CGO overhead.

### Scala/Spark (Aggregation Engine)
Spark's **distributed DataFrame API** is the gold standard for spatial joins on large geospatial datasets. Scala's functional style maps cleanly to the pipelined LST math (NDVI → Pv → Emissivity → LST). Target encoding of 50+ zoning categories is a single `groupBy` + `join`.

### Python (ML Training)
Python remains the **richest ML ecosystem**. Polars replaces pandas for 10–100x faster Parquet loading, XGBoost provides state-of-the-art gradient boosting with built-in feature importance, and the ecosystem's SHAP library enables the explainability required for academic review.

---

## 🚀 Quick Start

```bash
# Prerequisites: go 1.22+, java 17+, sbt 1.10+, python 3.12+, uv
make setup     # Install all deps across languages
make ingest    # Stage 1: Go ingestion worker pool
make process   # Stage 2: Scala/Spark aggregation
make train     # Stage 3: Python ML training
make all       # Full pipeline end-to-end
```

---

## 📁 Directory Layout

```
Helios/
├── Makefile                    # Cross-language orchestrator
├── docs/                       # Architectural documentation
├── ingestion-go/               # Stage 1: Concurrent ingestion engine
│   ├── cmd/ingest/main.go      # CLI entry point (+2 workers)
│   └── internal/
│       ├── config/             # Configuration parsing
│       ├── fetcher/            # STAC client + HTTP downloader
│       ├── parser/             # GeoTIFF / OSM → Record
│       └── worker/             # Bounded goroutine pool
├── processing-scala/           # Stage 2: Spark aggregation
│   ├── build.sbt
│   └── src/main/scala/helios/
├── ml-python/                  # Stage 3: ML training
│   ├── pyproject.toml
│   └── helios_ml/
└── staging/                    # Local data staging (git-ignored)
    ├── raw/                    # Stage 1 output (partitioned Parquet)
    └── dense/                  # Stage 2 output (feature matrix)
```

---

## 📖 Documentation

| Document | Description |
|----------|-------------|
| [Architecture](docs/architecture.md) | System design, data flow, design principles |
| [Phase 1 — Ingestion](docs/phase1-ingestion.md) | Go STAC client, Landsat discovery, Parquet export |
| [Phase 2 — Aggregation](docs/phase2-aggregation.md) | Spark spatial joins, LST math, target encoding |
| [Phase 3 — ML Training](docs/phase3-ml.md) | Polars loading, temporal split, XGBoost config |
| [Data Contracts](docs/data-contracts.md) | Parquet schemas, STAC API contract, compression |

---

## 🎯 Project Roadmap

- [x] **Phase 1.1**: Landsat Fetcher — STAC API discovery, worker pool, retry/backoff
- [ ] **Phase 1.2**: Vector Parser — Shapefile/GeoJSON to Record
- [ ] **Phase 1.3**: Raw Parquet Export — Partitioned columnar storage
- [ ] **Phase 2.1**: Spatial Alignment — Spark spatial join
- [ ] **Phase 2.2**: Math Pipeline — NDVI → Pv → ε → LST
- [ ] **Phase 2.3**: Target Encoding — High-cardinality encoding
- [ ] **Phase 2.4**: Feature Matrix — Dense Parquet output
- [ ] **Phase 3.1**: Data Loading — Polars lazy reader
- [ ] **Phase 3.2**: Temporal Split — Years 1-8 train, 9-10 test
- [ ] **Phase 3.3**: Model Training — XGBoost regressor
- [ ] **Phase 3.4**: Evaluation — SHAP, RMSE, feature importance

---

<p align="center">
  Built with ☀️ by Prathmesh Desai
</p>

<p align="center">
  <a href="https://github.com/pd241008">pd241008</a>
</p>
