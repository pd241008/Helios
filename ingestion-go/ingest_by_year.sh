#!/bin/bash
for year in {2026..2016}; do
    echo "======================================"
    echo "Ingesting Year $year..."
    echo "======================================"
    go run ./cmd/ingest -bbox 79.9469,12.8000,80.3450,13.2300 \
        -start-year $year -end-year $year \
        -max-cloud 30 -max-aoi-cloud 10 \
        -pc-source -fetch-split-window=false \
        -output-dir /mnt/f/helios-archive/staging/raw -workers 4
done
