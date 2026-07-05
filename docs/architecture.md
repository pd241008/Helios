# Helios Architecture

## Overview

Helios is a polyglot geospatial ML pipeline that predicts **Land Surface Temperature (LST)** for Chennai, India, using Landsat 8 satellite imagery and land-use/land-cover (LULC) features.

The pipeline is divided into three language-specific layers, each responsible for a distinct stage of data processing:

```mermaid
flowchart LR
    A["🌍 Landsat 8<br/>STAC API"]
    B["🛡️ Go<br/>Worker Pool"]
    C["📦 staging/raw/<br/>Partitioned Parquet"]
    D["⚡ Scala/Spark<br/>Aggregation"]
    E["📊 staging/dense/<br/>Feature Matrix"]
    F["🐍 Python/XGBoost<br/>ML Training"]
    G["📈 LST Model"]

    A -->|HTTP| B
    B -->|raw .parquet| C
    C --> D
    D -->|dense .parquet| E
    E --> F
    F --> G
```

## Design Principles

1. **Language for the job** — Go for I/O-bound ingestion, Scala/Spark for CPU-bound spatial joins, Python for fast prototyping of ML models.
2. **Parquet as the lingua franca** — All inter-stage communication uses Apache Parquet, providing columnar compression, schema enforcement, and zero-copy reads.
3. **Immutable staging** — Raw data is never modified in place; each stage reads from one directory and writes to the next.
4. **Graceful degradation** — All network calls have timeouts, retries, and backoff. Context cancellation propagates from SIGINT/SIGTERM to every goroutine.
5. **Reproducibility** — Parser seeds are derived from payload hashes, so identical input produces identical output.

## Pipeline Phases

```mermaid
flowchart TD
    subgraph "Phase 1 — Ingestion (Go)"
        A1[1.1 Landsat Fetcher<br/>STAC API → Scene Assets]
        A2[1.2 Vector Parser<br/>Shapefiles / GeoJSON]
        A3[1.3 Raw Parquet Export<br/>staging/raw/]
    end
    subgraph "Phase 2 — Aggregation (Scala/Spark)"
        B1[2.1 Spatial Alignment<br/>Pixel ↔ Zone Join]
        B2[2.2 Math Pipeline<br/>NDVI → Pv → ε → LST]
        B3[2.3 Target Encoding<br/>Label → Historical Mean]
        B4[2.4 Feature Matrix<br/>staging/dense/]
    end
    subgraph "Phase 3 — ML (Python)"
        C1[3.1 Polars Data Loading]
        C2[3.2 Temporal Split<br/>Train: 2014-21, Test: 2022-23]
        C3[3.3 XGBoost Training]
        C4[3.4 SHAP Evaluation<br/>RMSE + Feature Importance]
    end

    A1 --> A3
    A2 --> A3
    A3 --> B1
    B1 --> B2 --> B3 --> B4
    B4 --> C1 --> C2 --> C3 --> C4
```

## Repository Layout

```
Helios/
├── Makefile                    # Cross-language orchestration
├── docs/                       # Architectural documentation
├── ingestion-go/               # Stage 1: Concurrent ingestion engine
│   ├── cmd/ingest/main.go      # CLI entry point
│   └── internal/
│       ├── config/             # Configuration parsing
│       ├── fetcher/            # HTTP clients (STAC, USGS)
│       ├── parser/             # GeoTIFF / OSM → Record
│       └── worker/             # Bounded goroutine pool
├── processing-scala/           # Stage 2: Spark aggregation
│   ├── build.sbt
│   └── src/main/scala/helios/
├── ml-python/                  # Stage 3: ML training
│   ├── pyproject.toml
│   └── helios_ml/
└── staging/                    # Data staging (git-ignored)
    ├── raw/                    # Stage 1 output (partitioned Parquet)
    └── dense/                  # Stage 2 output (feature matrix)
```

## Data Flow Detail

| Step | Component | Input | Output | Description |
|------|-----------|-------|--------|-------------|
| 1.1  | Landsat Fetcher | STAC API query | Landsat scene assets (TIF) | Discover & download scenes for Chennai |
| 1.2  | Vector Parser | Shapefiles / GeoJSON | LULC records | Parse zoning and land-use vectors |
| 1.3  | Parquet Export | Raw rasters + vectors | `staging/raw/*.parquet` | Partitioned columnar storage |
| 2.1  | Spatial Alignment | Raw Parquet | Joined DataFrame | Assign zoning tags to pixels |
| 2.2  | Math Pipeline | Joined DataFrame | LST per pixel | NDVI → Pv → Emissivity → LST |
| 2.3  | Target Encoding | LST + zoning | Encoded DataFrame | Replace string labels with historical means |
| 2.4  | Feature Matrix | Encoded DataFrame | `staging/dense/matrix.parquet` | Dense numerical matrix |
| 3.1  | Data Loading | Dense matrix | Polars DataFrame | Fast columnar load |
| 3.2  | Temporal Split | DataFrame | Train/test splits | Years 1-8 train, 9-10 test |
| 3.3  | Model Training | Train split | XGBoost model | Predict LST from features |
| 3.4  | Evaluation | Test split | RMSE + feature importance | Validate and explain |

## Execution

```bash
make setup      # Install all dependencies
make ingest     # Stage 1: Go ingestion
make process    # Stage 2: Scala/Spark aggregation
make train      # Stage 3: Python ML training
make all        # Full end-to-end pipeline
```
