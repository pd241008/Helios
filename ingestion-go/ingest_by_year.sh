#!/bin/bash
for year in {2016..2026}; do
    echo "======================================"
    echo "Ingesting Year $year (Max 8 Scenes)..."
    echo "======================================"
    go run ./cmd/ingest -bbox 77.34,12.83,77.90,13.16 \
        -start-year $year -end-year $year \
        -max-cloud 30 -max-aoi-cloud 10 \
        -pc-source -fetch-split-window=false \
        -output-dir /mnt/f/helios-archive-bangalore/staging/raw \
        -limit 8 -workers 4
done
