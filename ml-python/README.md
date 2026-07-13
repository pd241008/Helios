# Helios — Stage 3: ML Training (Python)

## Caveat: split-window LST accuracy depends on atmospheric water vapor

The `LST_split_window` column consumed from the Scala pipeline uses a
**placeholder constant** (~2.0 g/cm²) for atmospheric water vapor `w` in the
split-window equation (see `processing-scala/README.md` — "Known limitations").
This placeholder introduces systematic error into the target values.

Consequently, **any R², RMSE, or MAE reported by the training pipeline should
be treated as preliminary** until a real water vapour source (MODIS MOD07,
NCEP reanalysis, or ERA5) is wired into the Scala processing layer and the
dense matrix is regenerated.  The model may appear to fit tighter than ground
truth would allow, because the error in `LST_split_window` is correlated
(rather than random) across scenes.
