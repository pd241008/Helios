#!/bin/bash
set -e

echo "=========================================================="
echo "    HELIOS OVERNIGHT SEQUENCE - A/B TEST & BANGALORE      "
echo "=========================================================="
echo "Starting at $(date)"

cd /root/workspace/workspace/03-Code/Projects/Legacy/Helios

echo ""
echo "--- [1/3] Running A/B Test Processing (25.1M Baseline) ---"
# Spark temp directory is explicitly configured in Makefile to point to F:
make process-abtest

echo ""
echo "--- [1.5/3] Checkpointing A/B Test Dense Matrix ---"
cp -r /mnt/f/helios-archive-baseline/staging/dense_abtest /mnt/f/helios-archive-baseline/dense_abtest_CHECKPOINT

echo ""
echo "--- [2/3] Running A/B Test Training ---"
make train-abtest

echo ""
echo "--- Generating Verification Bundle ---"
mkdir -p /mnt/f/helios-archive-baseline/metrics_abtest
BUNDLE="/mnt/f/helios-archive-baseline/metrics_abtest/verification_bundle.txt"
echo "Metrics:" > $BUNDLE
cat /mnt/f/helios-archive-baseline/metrics_abtest/metrics.json >> $BUNDLE
echo -e "\n\nFiles sizes:" >> $BUNDLE
ls -la /mnt/f/helios-archive-baseline/metrics_abtest/ >> $BUNDLE
echo "Verification Bundle Generated at $BUNDLE"

echo ""
echo "--- [2.5/3] Checkpointing A/B Test Metrics ---"
cp -r /mnt/f/helios-archive-baseline/metrics_abtest /mnt/f/helios-archive-baseline/metrics_abtest_CHECKPOINT

echo ""
echo "--- [3/3] Running Bangalore Data Ingestion ---"
make ingest-bangalore

echo ""
echo "--- [3.5/3] Checkpointing Bangalore Raw Data ---"
cp -r /mnt/f/helios-archive-bangalore/staging/raw /mnt/f/helios-archive-bangalore/raw_CHECKPOINT

echo ""
echo "=========================================================="
echo "    OVERNIGHT SEQUENCE COMPLETE!                          "
echo "=========================================================="
echo "Finished at $(date)"
