# Context: Dual-City Datasets (Bangalore & Chennai v2)

## Overview

Helios evaluates urban LST prediction on two Indian cities. Both dense
matrices are produced by the same Go ingestion + Scala spatial-join pipeline
and share an identical 20-column schema, so the ML stage treats them
symmetrically.

| | Bangalore | Chennai (v2) |
|---|---|---|
| BBox | 77.34, 12.83 -- 77.90, 13.16 | 79.9469, 12.80 -- 80.345, 13.23 |
| Landsat path/row | 144/051 | 142/051 |
| Dense matrix | `staging/dense/` (repo-local) | `/mnt/f/helios-archive-recent/staging/dense_chennai_v2` |
| Rows | 21,480,252 | 25,848,772 |
| Scenes ingested | 26 (cap: 8/year) | 43 |
| Scene period | 2016-04-21 -- 2025-12-10 | 2016-04-23 -- 2026-06-06 |
| STAC discovery filter | `eo:cloud_cover < 30%` | `eo:cloud_cover < 10%` (v1 used 30%) |
| AOI hard gate | **< 10%** (`-max-aoi-cloud`, rejects scene) | same |
| Achieved AOI cloud | mean 2.72%, max 9.26% | mean ≈2%, max 9.46% |

**AOI cloud** = fraction of cloudy QA_PIXEL pixels *inside the city bounding
box*, computed per scene by the ingestion worker — not the whole-scene
`eo:cloud_cover` from STAC. Every scene in both matrices passed the same
<10% AOI gate; the differing discovery pre-filters are cosmetic.

Chennai's full 43-scene inventory (scene IDs, dates, platform, AOI cloud %,
split assignment, row counts) is transcribed in
`table_B1_chennai_scenes.{md,csv}` alongside the ensemble reports.

## Superseded datasets (do not use for results)

- `dense_chennai_v1` / 60-scene backup (`staging/raw_backup_60_scenes`) —
  pre-v2 ingestion at a 30% cloud gate.
- The 18-scene / 10%-sample Chennai table in early manuscript drafts.
- `/mnt/f/helios-archive/reports/ml-ensemble-fullres-OLDSPLIT-do-not-use` —
  ensemble evaluated on the stale calendar-year markers (see ADR-005).

## Feature schema shared by both cities

10 model features after the leakage guard (ADR-001) and exclusions:
`lat`, `lon`, `lulc_class_encoded`, `zoning_category_encoded`, `ndvi`,
`B6_SWIR1`, `B5_NIR`, `B4_Red`, `doy_sin`, `doy_cos`.
Target: `lst` (split-window LST). Excluded as features: thermal precursors
(`ST_B10`, `bt10*`), emissivities, `ndbi`, `pv`, plus non-feature columns.
