# Verification

Fast verification of the artifact **without** re-running experiments.
For end-to-end reproduction see `REPRODUCE.md`.

## Step 1 — Verify shipped checkpoints

```bash
make verify
# or
python3 verification/verify_manifest.py
```

Expected output:

```
verify_manifest: PASS (2/2 entries)
```

Confirms `models/chennai_v1/lst_model.json` and
`models/chennai_v2/lst_model.json` match `manifest/checkpoint_sha256.txt`.

## Step 2 — Environment smoke test

```bash
cd ml-python && uv sync && uv run pytest -q
```

Confirms the Python environment resolves from `uv.lock` and the data-layer
tests pass (no dataset required).

## Step 3 — Match numbers to the paper

Open the shipped result files and compare against the paper tables:

| Paper table | Shipped file |
|---|---|
| Table 2 (Chennai single-model metrics) | `results/chennai_v2/metrics.json` |
| Table 3 (Chennai ensemble — partial) | `results/chennai_v2/ensemble_metrics_partial.json` |
| Table 5 (Bangalore ensemble) | see `results/README.md` |
| Figures 5–8 (SHAP) | `results/shap/*.png` |

## Step 4 — Load a shipped model (optional)

```python
import xgboost as xgb
bst = xgb.Booster()
bst.load_model("models/chennai_v2/lst_model.json")
print(best_iteration if (best := bst.attributes()) else "loaded")
```

Any downstream evaluation (e.g. SHAP via `ml-python/helios_ml/evaluate.py`)
can consume this checkpoint directly.
