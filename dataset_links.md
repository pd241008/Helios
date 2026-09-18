# Dataset Links and Integrity Anchors

Public sources for every dataset the pipeline consumes. Raw data is **not**
redistributed with the artifact; re-acquire from these anchors (see
`REPRODUCE.md` stage 1).

## Landsat 8/9 Collection 2 Level-2

| Property | Value |
|---|---|
| Primary STAC API | `https://planetarycomputer.microsoft.com/api/stac/v1` |
| Collection | `landsat-c2-l2` |
| Alternate STAC API | `https://landsatlook.usgs.gov/stac-server` |
| Asset signing | Planetary Computer SAS tokens (on-demand, `fetcher.SignPCURL`) |
| License | public domain (NASA/USGS) |

Query parameters used (both cities): temporal 2016-01-01 → 2026-12-31,
`eo:cloud_cover < 30%` (Bangalore) / `< 10%` (Chennai v2) discovery
pre-filter, hard AOI cloud gate `< 10%` computed per scene from QA_PIXEL
inside the city bbox (claim C8).

## Zoning / LULC polygons

| Property | Value |
|---|---|
| Source | OpenStreetMap via Overpass API |
| Fetch tool | `tools/fetch_zoning.py` (writes `staging/raw/zoning.geojson`) |
| License | ODbL — © OpenStreetMap contributors |
| Snapshot used | 2026-07/08 (paper figures) — living data, will not re-fetch identically |

## Atmospheric coefficients

Landsat 8/9 Band 10/11 Planck constants K1/K2 as published by USGS
(hardcoded in `processing-scala/src/main/scala/helios/LSTMath.scala` and
`ml-python/run_dry_run.py`). Water vapor assumed 2.0 g/cm²
(`LIMITATIONS.md` §11).

## Integrity anchors

Because raw scenes are re-acquired rather than shipped, integrity is
anchored at two points instead:

1. **Scene selection:** counts + AOI cloud statistics per city
   (`results/scene_inventory.md`) — a re-ingestion should recover the same
   scene set (Landsat archive is immutable) with matching AOI cloud stats.
2. **Post-aggregation:** dense-matrix schema + row counts
   (`docs/data-contracts.md`: 21,480,252 rows Bangalore / 25,848,772
   rows Chennai v2).

Shipped *derived* artifacts (models) carry direct SHA-256 anchors in
`manifest/checkpoint_sha256.txt`.
