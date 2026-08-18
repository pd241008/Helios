# ADR 001: Explicit Target Leakage Guard in ML Training

## Status
Accepted (2026-08-18)

## Context
During initial machine learning model evaluation, the XGBoost model achieved an R² score of `1.0` (perfect accuracy) and SHAP feature importance indicated that `ST_B10` alone was responsible for all predictive power. 

Because Land Surface Temperature (LST) is physically derived from thermal band data (specifically `ST_B10` and atmospheric corrections), including these raw thermal bands in the input feature matrix results in severe data leakage. The model was not predicting urban heat—it was simply reverse-engineering the algorithmic derivation of the target.

## Decision
We implemented a hardcoded "Leakage Guard" directly inside the core data loading pipeline in `ml-python/helios_ml/train.py`.

Before features (`X`) and targets (`y`) are split, we explicitly drop the following known thermal precursors:
- `ST_B10`
- `bt10`
- `bt11`
- `bt10_minus_bt11`

If these columns exist in the incoming Parquet matrix, they are silently removed from `X`. Additionally, to prevent regressions, an explicit `ValueError` is raised if any thermal bands somehow survive into the final feature list passed to XGBoost.

## Consequences
**Positive:** 
- The model is forced to predict LST using causal/environmental factors (NDVI, spatial zoning) rather than thermal emission.
- True predictive baseline was established at `R² = ~0.65`.

**Negative:**
- Requires hardcoding column names into the pipeline. If upstream naming changes, the guard could be bypassed unless the safety assertion catches it.
