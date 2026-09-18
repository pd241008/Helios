# Results

Archived experimental outputs backing the paper's tables and figures.
Provenance is explicit per file — transcribed files are marked as such.

```
results/
├── chennai_v2/
│   ├── metrics.json                      SHIPPED (pipeline output)
│   ├── ensemble_metrics_partial.json     SHIPPED (pipeline output, partial run)
│   └── ensemble_metrics.transcribed.csv  TRANSCRIBED from manuscript v12 (Table 3)
├── bangalore/
│   └── ensemble_metrics.transcribed.csv  TRANSCRIBED from manuscript v12 (Table 5)
├── archive/
│   └── metrics_unlabeled_2026-08-19_run.json   PROVENANCE ONLY — do not cite
├── shap/
│   ├── chennai/                          SHIPPED figures (paper Figs. 5–6)
│   ├── bangalore/                        SHIPPED figures (paper Figs. 7–8)
│   └── appendix_*.png                    SHIPPED (appendix validation figures)
└── scene_inventory.md                    Aggregate scene facts (C8)
```

## Provenance notes

- **Bangalore per-model JSON was not persisted.** The generating script and
  split policy are intact; the CSV here is a faithful transcription of
  manuscript v12 Table 5. Regeneration path: `REPRODUCE.md` stage 3
  (`--split-strategy dynamic`). See `LIMITATIONS.md` item 4.
- **Chennai ensemble JSON is partial** (2 of 10 rows). Table 3 transcription
  covers the remaining rows. See `LIMITATIONS.md` item 5.
- The unlabeled 2026-08-19 archive run documents the stale-split failure
  mode that motivated ADR-005. Do not cite.
