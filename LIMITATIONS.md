# Limitations

Explicit boundaries of this artifact. Read before citing numbers.

## Data

1. **Raw datasets are not redistributed.** Landsat 8/9 scenes (~70 MB each)
   and OSM zoning extracts are re-acquired from public APIs
   (`dataset_links.md`). Public mirrors can change; re-ingested data may
   differ from the archived dense matrices (see
   `REPRODUCIBILITY_LEVELS.md`, L3/L4).
2. **Dense matrices are not shipped.** 21.5M-row (Bangalore) and
   25.8M-row (Chennai) parquet datasets exceed artifact size budgets;
   they are regenerable via `REPRODUCE.md` stages 1–2.
3. **Zoning scope.** All models train only on pixels inside municipal
   zoning polygons (26.7% Chennai, 34.52% Bangalore of scene footprints).
   Predictions outside zoned areas are out of scope by construction.

## Results provenance

4. **Bangalore per-model JSON — recovered 2026-09-19.** The ensemble run's
   raw `ensemble_metrics.json` (written 2026-08-21 11:35 IST,
   `ml-ensemble-fullres-v2-bangalore` on the archive volume) survives and
   is now shipped at `results/bangalore/ensemble_metrics.json`. All 10
   rows match manuscript Table 5 to 3 decimals (sha256 recorded in
   `manifest/evidence_sha256.txt`). An earlier revision of this file
   wrongly stated that the run's JSON was lost in a cleanup.
5. **Chennai full ensemble JSON — recovered 2026-09-19.** The complete
   10-row run output (`ml-ensemble-fullres-v3-chennai-fixedwindow`,
   2026-08-22) is shipped at `results/chennai_v2/ensemble_metrics.json`
   and matches Table 3; the earlier partial archive
   (`ensemble_metrics_partial.json`) and the Table 3 transcription are
   retained for provenance.
6. **Scene inventory.** Per-scene CSVs for both cities are now shipped
   (`results/bangalore/scene_inventory.csv`, 26 scenes;
   `results/chennai_v2/scene_inventory.csv`, 43 scenes), generated from
   the archived per-scene `scene_metadata.json` and cross-checked against
   the aggregates in `results/scene_inventory.md`.
7. **`results/archive/metrics_unlabeled_2026-08-19_run.json`** is retained
   for provenance only (negative R², unlabeled configuration — likely a
   stale-split run per ADR-005). Do not cite it.

## Modeling

8. **Bangalore test-window thinness.** The rolling 12-month test window
   (3.27M rows, 4 scenes) is seasonally narrow; individual models score
   R² 0.27–0.36 and the ensemble 0.529. Cross-city comparison of absolute
   R² is therefore not apples-to-apples (paper §Discussion).
9. **SHAP is sampled.** SHAP values are computed on n=10,000 randomly
   sampled test rows (fixed seed), not the full test set; the sample size
   is recorded per model in the ensemble metrics.
10. **Single seed.** Reported runs use seed 42; no multi-seed variance
    bands are claimed.
11. **Water vapor assumption.** Atmospheric water vapor is assumed at
    2.0 g/cm² pending per-scene integration (paper §Methods).
