# ADR 003: Traceback Logging for SHAP Explainer Failures

## Status
Accepted (2026-08-18)

## Context
Generating SHAP (SHapley Additive exPlanations) values is computationally expensive. When attempting to run the `TreeExplainer` on a dense 25M-row Parquet feature matrix, the process failed silently, writing the `metrics.json` but omitting the SHAP dependency plots from the output directory.

The root cause was a broad `except Exception: pass` block surrounding the SHAP computation. This try/catch was originally implemented to prevent non-critical interpretability errors from failing the entire ML pipeline, but its silence obscured critical OOM (Out-of-Memory) and threading errors occurring deep within the SHAP C-extensions.

## Decision
We replaced the silent `pass` with explicit traceback logging:
```python
except Exception as e:
    import traceback
    with open(f"{output_dir}/shap_error_traceback.log", "w") as f:
        traceback.print_exc(file=f)
```

## Consequences
**Positive:** 
- Explainer failures still do not crash the pipeline (metrics and models are still saved).
- Developers now have a complete stack trace written directly to the output artifact folder to diagnose OOMs or algorithmic incompatibilities.

**Negative:**
- Introduces an additional `.log` artifact.
