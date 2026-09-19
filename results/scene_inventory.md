# Scene Inventory (aggregate)

Aggregate scene-acquisition facts per city. Per-scene CSVs are shipped:
`bangalore/scene_inventory.csv` (26 scenes) and
`chennai_v2/scene_inventory.csv` (43 scenes), generated from the archived
per-scene `scene_metadata.json` files and consistent with the table below
(see `LIMITATIONS.md` item 6).

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
