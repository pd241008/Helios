import json
p = "/mnt/f/helios-archive/reports/ml-ensemble/ensemble_metrics.json"
try:
    with open(p, "r") as f: data = json.load(f)
    data.pop("XGBoost (Base)", None)
    data.pop("XGBoost (Tuned)", None)
    with open(p, "w") as f: json.dump(data, f, indent=2)
except Exception as e:
    print(e)
