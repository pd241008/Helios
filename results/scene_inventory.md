# Scene Inventory (aggregate)

Aggregate scene-acquisition facts per city. The per-scene table
(`table_B1_chennai_scenes.{md,csv}`) referenced by earlier drafts was not
persisted; regenerating it is possible via `ingestion-go/cmd/check_all_aoi_cloud`
(claim C8). See `LIMITATIONS.md` item 6.

| | Bangalore | Chennai (v2) |
|---|---|---|
| Scenes retained | 26 of 255 candidates | 43 |
| Scene period | 2016-04-21 → 2025-12-10 | 2016-04-23 → 2026-06-06 |
| Discovery filter | `eo:cloud_cover < 30%` | `eo:cloud_cover < 10%` |
| AOI hard gate | < 10% (QA_PIXEL-derived, per scene) | < 10% |
| Achieved AOI cloud | mean 2.72%, max 9.26% | mean ≈2%, max 9.46% |
| Dense matrix rows | 21,480,252 | 25,848,772 |
| Zoning coverage (inner join) | 34.52% | 26.7% |
| Path/row | 144/051 | 142/051 |
