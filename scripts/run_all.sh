#!/bin/bash
set -e
echo "Cleaning up dense directory..."
rm -rf /mnt/f/helios-archive/staging/dense
echo "Starting pipeline..."
make process > /tmp/make_process.log 2>&1
echo "Make process done, starting ensemble..."
cd ml-python
uv run python -m helios_ml.ensemble --sample-strategy systematic-grid --sample-rate 0.05 > /tmp/ensemble_run.log 2>&1
echo "Ensemble done."
