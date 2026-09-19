# Results

Archived experimental outputs backing the paper's tables and figures.
Provenance is explicit per file — transcribed files are marked as such.

```
results/
├── chennai_v2/
│   ├── metrics.json                      SHIPPED (pipeline output)
│   ├── ensemble_metrics.json             SHIPPED (raw 10-row run output, 2026-08-22)
│   ├── ensemble_metrics_partial.json     SHIPPED (pipeline output, partial run)
│   ├── split_evidence.txt                SHIPPED (run-generated split audit)
│   ├── scene_inventory.csv               GENERATED from archived scene_metadata.json (43 scenes)
│   └── ensemble_metrics.transcribed.csv  TRANSCRIBED from manuscript v12 (Table 3)
├── bangalore/
│   ├── ensemble_metrics.json             SHIPPED (raw 10-row run output, 2026-08-21)
│   ├── single_model_metrics.json         SHIPPED (pipeline output, single XGBoost)
│   ├── split_evidence.txt                SHIPPED (run-generated split audit)
│   ├── scene_inventory.csv               GENERATED from archived scene_metadata.json (26 scenes)
│   └── ensemble_metrics.transcribed.csv  TRANSCRIBED from manuscript v12 (Table 5)
├── archive/
│   └── metrics_unlabeled_2026-08-19_run.json   PROVENANCE ONLY — do not cite
├── shap/
│   ├── chennai/                          SHIPPED figures (paper Figs. 5–6)
│   ├── bangalore/                        SHIPPED figures (paper Figs. 7–8)
│   └── appendix_*.png                    SHIPPED (appendix validation figures)
├── artifact_figures/
│   ├── bangalore_v2/                     ARTIFACT-ONLY 32-figure set, v2 ensemble run (2026-08-21) — not used in paper
│   └── chennai_v3/                       ARTIFACT-ONLY 32-figure set, v3 ensemble run (2026-08-22) — not used in paper
└── scene_inventory.md                    Aggregate scene facts (C8)
```

The corresponding trained ensemble checkpoints are shipped under
`models/bangalore_ensemble_v2/` and `models/chennai_ensemble_v3/`
(8 `.joblib` files each). All of the above is covered by
`manifest/evidence_sha256.txt`.

## Provenance notes

- **Bangalore per-model JSON — recovered.** The ensemble run's raw
  `ensemble_metrics.json` survives on the archive volume
  (`helios-archive/reports/ml-ensemble-fullres-v2-bangalore/`, written
  2026-08-21 11:35 IST) and is now shipped here. All 10 rows match
  manuscript Table 5 (and the transcription below) to 3 decimals;
  Tuned Ensemble R² = 0.5292495489 → 0.529. sha256:
  `f7cf99066dad26136967a2096d9e9e7988da367688d526f8f3dbbc8a52132395`.
  An earlier revision of this file and of `LIMITATIONS.md` item 4
  wrongly stated the JSON "was lost in a cleanup" — it never was.
- **Chennai ensemble JSON — recovered.** The complete 10-row output of
  the fixed-window run (`ml-ensemble-fullres-v3-chennai-fixedwindow`,
  2026-08-22 09:39 IST) is shipped as `chennai_v2/ensemble_metrics.json`
  and matches Table 3. The partial archive and the transcription are
  retained for provenance.
- **Superseded runs.** The 2026-08-19 16:52 IST
  `ml-ensemble/ensemble_metrics.json` on the archive volume (Tuned
  Ensemble R² = 0.5200, per-model R² ≈ 0) is the pre-ADR-005
  stale-split run. It explains the 0.520 that appears in the manuscript
  conclusion; Table 5's 0.529 is backed by the recovered 2026-08-21 run.
  Retained on the archive volume only; do not cite.
- **Scene inventories.** `bangalore/scene_inventory.csv` (26 scenes) and
  `chennai_v2/scene_inventory.csv` (43 scenes) are generated from the
  per-scene `scene_metadata.json` files archived with the raw staging
  data. Aggregates (counts, period, mean/max AOI cloud) match
  `scene_inventory.md` exactly: Bangalore mean 2.72% / max 9.26%,
  Chennai mean ≈2% / max 9.46%. The `split` column reflects each city's
  ADR-005 policy (dynamic 12-month cutoff 2024-12-10 for Bangalore;
  calendar-year ≥ 2025 markers for Chennai).
- **SHAP figure sets.** `shap/chennai/`, `shap/bangalore/` and the
  `shap/appendix_*.png` files are the figures used in the paper
  (Figs. 5–8 plus appendix). `artifact_figures/bangalore_v2/` and
  `artifact_figures/chennai_v3/` hold the complete 32-figure sets from
  the archived full-resolution ensemble runs — artifact-only outputs
  that were **not** used in the paper; some same-named files differ from
  the paper figures because those came from earlier runs.
- The unlabeled 2026-08-19 archive run documents the stale-split failure
  mode that motivated ADR-005. Do not cite.
