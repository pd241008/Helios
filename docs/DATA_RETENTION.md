# Data Retention Policy

## Overview

This document defines how staging data is managed during Helios ingestion
runs. The goal is to prevent unbounded disk growth during multi-year
ingestion runs (40-90x more data than the Chennai 2023 dry run).

## Per-scene lifecycle

Each Landsat scene follows this lifecycle:

```
Download TIFFs → Parse to Parquet → Validate (PAR1 footer) → Delete TIFFs
```

1. **Download**: Worker pool downloads 5 signed TIFF bands per scene from
   Planetary Computer (~70 MB/scene).
2. **Parse**: `ParquetStreamWriter` writes records directly to parquet
   (~2.5-3 GB/scene for 185km×185km full-scene coverage).
3. **Validate**: PAR1 footer is confirmed by the parquet library on `Close()`.
4. **Delete**: Raw TIFFs are automatically removed by `cleanupSceneTIFFs()`
   in `worker/pool.go` after successful parquet write.

**Why delete TIFFs?** SAS-signed URLs from Planetary Computer are short-lived
(~1 hour). The TIFFs on disk are unsigned copies. If reprocessing is needed
(e.g., parser logic changes), scenes can be re-downloaded and re-signed from
PC — the STAC metadata is preserved in `scene_metadata.json`.

## staging/ directory structure

```
staging/
├── raw/
│   ├── landsat/          # Per-scene parquet files (source of truth)
│   │   ├── LC08_*.parquet
│   │   ├── LC08_*/       # Scene dirs (scene_metadata.json only after cleanup)
│   │   └── ...
│   └── zoning.geojson    # LULC zone polygons
├── dense/                # Stage 2 output (feature matrices)
│   └── year=YYYY/
│       └── split=train|test/
└── DRY_RUN_LOG.md        # Dry run findings
```

## What gets kept

| Artifact | Retention | Rationale |
|----------|-----------|-----------|
| `staging/raw/landsat/*.parquet` | **Permanent** | Source of truth for all downstream analysis |
| `staging/raw/landsat/*/scene_metadata.json` | **Permanent** | K1/K2 constants, acquisition datetime, WRS path/row |
| `staging/raw/zoning.geojson` | **Permanent** | LULC zone definitions |
| `staging/dense/` output | **Permanent** | Feature matrices for ML training |
| Raw `.tif` files | **Deleted after parquet write** | Re-downloadable from PC |
| `staging/temp/` | **Never created** | Removed from workflow; was a pre-fix artifact |
| Spark scratch dirs | **Cleaned after run** | Runtime-only; never persistent |

## What gets deleted

| Artifact | When | How |
|----------|------|-----|
| Raw `.tif` per-band files | After successful parquet write | `cleanupSceneTIFFs()` in `worker/pool.go` |
| Spark local/shuffle dirs | After successful run | `spark.local.dir` cleanup or manual |
| `/tmp/*.log` | After run verification | Manual or CI cleanup |

## Disk budget estimates

Per-scene disk usage after cleanup:
- Parquet: ~2.5-3.0 GB (185km×185km scene, 4 bands, ~150M records)
- Scene metadata: ~1 KB
- **Total per scene: ~3 GB**

10-year Landsat 8/9 archive estimate:
- ~900 scenes/year × 10 years = ~9,000 scenes
- ~9,000 scenes × 3 GB = **~27 TB** (full resolution, all zones)
- With spatial filtering to analysis bbox: ~1% of scenes = **~270 GB**

For the Chennai analysis (5 zones, ~1% of scene area):
- Zone-matched pixels: ~900K per scene × 9,000 scenes = ~8.1B pixels
- At 10% sample: ~810M pixels × 21 columns × 8 bytes = **~130 GB**

## Automatic cleanup

The `cleanupSceneTIFFs()` function in `ingestion-go/internal/worker/pool.go`
runs automatically after each successful `WriteStreaming()` call. It:

1. Lists all `.tif` files in the scene directory
2. Removes each one
3. Logs the count of removed files
4. Continues even if individual removals fail (non-fatal)

This ensures disk usage stays bounded without manual intervention.

## External drive archive

Validated artifacts are synced to an external drive via `rsync`:

| Item | Makefile target | Archive path |
|------|----------------|--------------|
| Raw parquet files | `make archive-raw` | `/mnt/f/helios-archive/staging/raw/landsat/` |
| Dense matrices | `make archive-dense` | `/mnt/f/helios-archive/staging/dense/` |
| ML reports | `make archive-reports` | `/mnt/f/helios-archive/reports/` |
| **Full sync** | `make archive` | `/mnt/f/helios-archive/` |

**Drive details:**
- Mount: `/mnt/f` (drive F: in Windows, "Personal Use" label)
- Total: 931.5 GB, ~276 GB free (as of 2026-07-15)
- WSL2 auto-mount: run `mount -t drvfs F: /mnt/f` if F: is not visible after WSL restart

**10-Year Ingestion Workflow:**
1. **Ingest**: Direct the Go ingestion worker's output (`--output-dir`) to `/mnt/f/helios-archive/staging/raw` or run frequent `make archive` syncs. The local SSD is too small to hold 270 GB of raw parquet permanently.
2. **Process (Spark)**: Keep Spark local scratch and shuffle directories (`spark.local.dir`) on the local SSD for fast I/O. Do NOT run Spark shuffle against the USB-attached external drive.
3. **Train (Python)**: ML training and report generation will pull from the archive (or the `make archive` synced copies) and save models/reports to `reports/`, which are then archived.
4. **Cleanup**: Transient work (like Spark temp files) remains local and is cleaned up automatically, leaving only the validated long-lived data on `/mnt/f/helios-archive/`.

### Archive disk budget

| Dataset | Size (Chennai 2023) | Full 10-year estimate |
|---------|--------------------|-----------------------|
| Raw parquet (7 scenes) | 19.9 GB | ~27 TB (full scene) / ~270 GB (filtered) |
| Dense matrix | 2.1 MB | ~130 GB (10% sample, 9K scenes) |
| Reports | 15 MB | Negligible |
| **Total archive** | **~20 GB** | **~270 GB–27 TB** depending on spatial filter |
