
# ╔══════════════════════════════════════════════════════════════════╗
# ║  Helios — Cross-Language Pipeline Orchestrator                  ║
# ║  Targets: setup | ingest | process | train | all | clean        ║
# ╚══════════════════════════════════════════════════════════════════╝

SHELL       := /bin/bash
.DEFAULT_GOAL := help

# ── Paths ─────────────────────────────────────────────────────────
ROOT_DIR    := $(shell pwd)
GO_DIR      := $(ROOT_DIR)/ingestion-go
SCALA_DIR   := $(ROOT_DIR)/processing-scala
PY_DIR      := $(ROOT_DIR)/ml-python
AOI ?= chennai

ifeq ($(AOI),bangalore)
  STAGING_DIR := /mnt/f/helios-archive-bangalore/staging
  BBOX_LON_MIN := 77.34
  BBOX_LON_MAX := 77.90
  BBOX_LAT_MIN := 12.83
  BBOX_LAT_MAX := 13.16
else
  STAGING_DIR := /mnt/f/helios-archive/staging
  BBOX_LON_MIN := 79.9469
  BBOX_LON_MAX := 80.3450
  BBOX_LAT_MIN := 12.8000
  BBOX_LAT_MAX := 13.2300
endif

# ── External drive (F: / 931 GB, "Personal Use") ─────────────────
ARCHIVE_DIR := /mnt/f/helios-archive

# ── Ensure staging dirs exist ─────────────────────────────────────
$(STAGING_DIR)/raw $(STAGING_DIR)/dense:
	@mkdir -p $@

.PHONY: help setup setup-go setup-scala setup-python \
        ingest process train all clean lint test \
        archive archive-raw archive-dense archive-reports sync-check

# ── Help ──────────────────────────────────────────────────────────
help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*##' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*##"}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

# ══════════════════════════════════════════════════════════════════
#  SETUP
# ══════════════════════════════════════════════════════════════════

setup: setup-go setup-scala setup-python ## Install all dependencies
	@echo "✓ All environments ready."

setup-go: ## Download Go modules
	cd $(GO_DIR) && go mod download && go mod verify

setup-scala: ## Fetch Scala/SBT dependencies
	cd $(SCALA_DIR) && sbt update

setup-python: ## Create venv and sync Python deps via uv
	cd $(PY_DIR) && uv sync

# ══════════════════════════════════════════════════════════════════
#  PIPELINE STAGES
# ══════════════════════════════════════════════════════════════════

ingest: $(STAGING_DIR)/raw ## Run Go ingestion worker pool
	@echo "═══ Stage 1: Ingestion (Go) ═══"
	cd $(GO_DIR) && go run ./cmd/ingest \
		--output-dir $(STAGING_DIR)/raw \
		--stac-url https://planetarycomputer.microsoft.com/api/stac/v1 \
		--bbox 79.9469,12.8,80.345,13.23 \
		--start-year 2016 --end-year 2026 \
		--max-cloud 30 \
		--workers 4
	@echo "✓ Raw parquet files written to $(STAGING_DIR)/raw"

ingest-bangalore: ## Prep Bangalore Data Download
	@echo "═══ Stage 1: Ingestion (Go) [Bangalore] ═══"
	@mkdir -p /mnt/f/helios-archive-bangalore/staging/raw
	cd $(GO_DIR) && go run ./cmd/ingest \
		--output-dir /mnt/f/helios-archive-bangalore/staging/raw \
		--stac-url https://planetarycomputer.microsoft.com/api/stac/v1 \
		--bbox 77.34,12.83,77.90,13.16 \
		--start-year 2016 --end-year 2026 \
		--max-cloud 30 \
		--workers 4
	@echo "✓ Bangalore raw parquet files written to /mnt/f/helios-archive-bangalore/staging/raw"

process: $(STAGING_DIR)/dense ## Run Scala/Spark aggregation
	@echo "═══ Stage 2: Processing (Scala/Spark) [AOI=$(AOI)] ═══"
	cd $(SCALA_DIR) && java -Xmx6g \
		-Dspark.helios.bbox.lonMin=$(BBOX_LON_MIN) \
		-Dspark.helios.bbox.lonMax=$(BBOX_LON_MAX) \
		-Dspark.helios.bbox.latMin=$(BBOX_LAT_MIN) \
		-Dspark.helios.bbox.latMax=$(BBOX_LAT_MAX) \
		--add-opens=java.base/sun.nio.ch=ALL-UNNAMED \
		--add-opens=java.base/java.lang=ALL-UNNAMED \
		--add-opens=java.base/java.lang.reflect=ALL-UNNAMED \
		--add-opens=java.base/java.nio=ALL-UNNAMED \
		--add-opens=java.base/java.io=ALL-UNNAMED \
		--add-opens=java.base/java.util=ALL-UNNAMED \
		-cp target/scala-2.13/helios-processing-assembly-0.1.0.jar helios.Main \
		--input $(STAGING_DIR)/raw \
		--output $(STAGING_DIR)/dense \
		--zoning-path $(STAGING_DIR)/raw/zoning.geojson \
		--train-year-start 2016 \
		--train-year-end 2024 \
		--test-year-start 2025 \
		--test-year-end 2026
	@echo "✓ Dense matrix written to $(STAGING_DIR)/dense"

train: ## Run Python ML training
	@echo "═══ Stage 3: Training (Python/XGBoost) ═══"
	cd $(PY_DIR) && uv run python -m helios_ml.train \
		--data-dir $(STAGING_DIR)/dense \
		--reports-dir /mnt/f/helios-archive/metrics
	@echo "✓ Model saved."

# ══════════════════════════════════════════════════════════════════
#  AB TEST TARGETS (Isolated Baseline Run)
# ══════════════════════════════════════════════════════════════════

process-abtest: ## Run Scala/Spark aggregation on the 60G baseline data to generate strict 25.1M row matrix with new features
	@echo "═══ Stage 2: Processing (AB Test Baseline) ═══"
	@mkdir -p /mnt/f/helios-archive-baseline/staging/tmp
	cd $(SCALA_DIR) && java -Xmx6g -Dspark.local.dir=/mnt/f/helios-archive-baseline/staging/tmp --add-opens=java.base/sun.nio.ch=ALL-UNNAMED --add-opens=java.base/java.lang=ALL-UNNAMED --add-opens=java.base/java.lang.reflect=ALL-UNNAMED --add-opens=java.base/java.nio=ALL-UNNAMED --add-opens=java.base/java.io=ALL-UNNAMED --add-opens=java.base/java.util=ALL-UNNAMED -cp target/scala-2.13/helios-processing-assembly-0.1.0.jar helios.Main \
		--input /mnt/f/helios-archive-baseline/staging/raw \
		--output /mnt/f/helios-archive-baseline/staging/dense_abtest \
		--zoning-path /mnt/f/helios-archive-baseline/staging/raw/zoning.geojson \
		--train-year-start 2016 \
		--train-year-end 2024 \
		--test-year-start 2025 \
		--test-year-end 2026
	@echo "✓ Strict AB-test Dense matrix written to /mnt/f/helios-archive-baseline/staging/dense_abtest"

train-abtest: ## Run Python ML training on the strict AB test baseline matrix
	@echo "═══ Stage 3: Training (AB Test Baseline) ═══"
	cd $(PY_DIR) && uv run python -m helios_ml.train \
		--data-dir /mnt/f/helios-archive-baseline/staging/dense_abtest \
		--reports-dir /mnt/f/helios-archive-baseline/metrics_abtest
	@echo "✓ AB test Model saved."

# ══════════════════════════════════════════════════════════════════
#  COMPOSITE TARGETS
# ══════════════════════════════════════════════════════════════════

all: ingest process train ## Run full pipeline end-to-end
	@echo "══════════════════════════════════════════"
	@echo "  Helios pipeline complete."
	@echo "══════════════════════════════════════════"

# ══════════════════════════════════════════════════════════════════
#  QUALITY
# ══════════════════════════════════════════════════════════════════

lint: ## Lint all languages
	cd $(GO_DIR)    && go vet ./...
	cd $(SCALA_DIR) && sbt scalafmtCheck
	cd $(PY_DIR)    && uv run ruff check .

test: ## Run tests across all languages
	cd $(GO_DIR)    && go test ./... -v -race
	cd $(SCALA_DIR) && sbt test
	cd $(PY_DIR)    && uv run pytest -v

# ══════════════════════════════════════════════════════════════════
#  CLEANUP
# ══════════════════════════════════════════════════════════════════

clean: ## Remove local build artifacts only (preserves F:\ drive staging data)
	rm -rf $(GO_DIR)/bin $(SCALA_DIR)/target $(PY_DIR)/.venv $(PY_DIR)/__pycache__ $(PY_DIR)/.pytest_cache
	cd $(GO_DIR)    && go clean -cache
	cd $(SCALA_DIR) && sbt clean
	rm -rf $(PY_DIR)/models
	@echo "✓ Local build artifacts cleaned. F:\ drive data preserved."

# ══════════════════════════════════════════════════════════════════
#  ARCHIVE (external drive — F: /mnt/f/helios-archive)
# ══════════════════════════════════════════════════════════════════

mount-check: ## Verify external drive is actually mounted (prevents local aliasing)
	@mount | grep -q "/mnt/f type 9p" || mount | grep -q "/mnt/f type drvfs" || \
		(echo "ERROR: /mnt/f is not mounted as a remote filesystem! Run 'sudo mount -t drvfs F: /mnt/f' first." && exit 1)

archive-raw: mount-check ## Sync raw parquet to external drive
	@echo "═══ Archiving raw parquet → $(ARCHIVE_DIR)/staging/raw/ ═══"
	@mkdir -p $(ARCHIVE_DIR)/staging/raw/landsat
	rsync -av $(STAGING_DIR)/raw/landsat/*.parquet $(ARCHIVE_DIR)/staging/raw/landsat/
	rsync -av $(STAGING_DIR)/raw/zoning.geojson $(ARCHIVE_DIR)/staging/raw/ 2>/dev/null || true
	@echo "✓ Raw archived."

archive-dense: mount-check ## Sync dense matrices to external drive
	@echo "═══ Archiving dense matrix → $(ARCHIVE_DIR)/staging/dense/ ═══"
	@mkdir -p $(ARCHIVE_DIR)/staging/dense
	rsync -av $(STAGING_DIR)/dense/ $(ARCHIVE_DIR)/staging/dense/
	@echo "✓ Dense archived."

archive-reports: mount-check ## Sync ML reports to external drive
	@echo "═══ Archiving reports → $(ARCHIVE_DIR)/reports/ ═══"
	@mkdir -p $(ARCHIVE_DIR)/reports
	rsync -av $(PY_DIR)/reports/ $(ARCHIVE_DIR)/reports/
	@echo "✓ Reports archived."

archive: mount-check archive-raw archive-dense archive-reports ## Sync all validated data to external drive
	@echo "════════════════════════════════════════"
	@echo "  Archive sync complete."
	@echo "  Target: $(ARCHIVE_DIR)"
	@echo "════════════════════════════════════════"

sync-check: ## Verify archive matches local staging (dry-run rsync)
	@echo "═══ Checking archive sync status ═══"
	@rsync -avn $(STAGING_DIR)/raw/landsat/*.parquet $(ARCHIVE_DIR)/staging/raw/landsat/ 2>&1 | tail -5
	@rsync -avn $(STAGING_DIR)/dense/ $(ARCHIVE_DIR)/staging/dense/ 2>&1 | tail -5
	@echo "═══ Archive disk usage ═══"
	@du -sh $(ARCHIVE_DIR) 2>/dev/null || echo "Archive dir not found"
