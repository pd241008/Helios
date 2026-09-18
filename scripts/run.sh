kpython -c '
import json
p = "/mnt/f/helios-archive/reports/ml-ensemble/ensemble_metrics.json"
with open(p, "r") as f: data = json.load(f)
data.pop("XGBoost (Base)", None)
data.pop("XGBoost (Tuned)", None)
with open(p, "w") as f: json.dump(data, f, indent=2)
'
cd /root/workspace/workspace/03-Code/Projects/Legacy/Helios/ml-python
uv run python -m helios_ml.ensemble --data-dir /mnt/f/helios-archive-bangalore/staging/dense --sample-strategy systematic-grid --sample-rate 0.1
