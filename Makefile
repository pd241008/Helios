
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
STAGING_DIR := $(ROOT_DIR)/staging

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
		--start-year 2023 --end-year 2023 \
		--max-cloud 10 \
		--workers 8
	@echo "✓ Raw parquet files written to $(STAGING_DIR)/raw"

process: $(STAGING_DIR)/dense ## Run Scala/Spark aggregation
	@echo "═══ Stage 2: Processing (Scala/Spark) ═══"
	cd $(SCALA_DIR) && sbt "runMain helios.Main \
		--input $(STAGING_DIR)/raw \
		--output $(STAGING_DIR)/dense"
	@echo "✓ Dense matrix written to $(STAGING_DIR)/dense"

train: ## Run Python ML training
	@echo "═══ Stage 3: Training (Python/XGBoost) ═══"
	cd $(PY_DIR) && uv run python -m helios_ml.train \
		--data-dir $(STAGING_DIR)/dense \
		--model-out $(PY_DIR)/models/lst_model.json
	@echo "✓ Model saved."

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

clean: ## Remove all build artifacts and staging data
	rm -rf $(STAGING_DIR)
	cd $(GO_DIR)    && go clean -cache
	cd $(SCALA_DIR) && sbt clean
	rm -rf $(PY_DIR)/.venv $(PY_DIR)/models
	@echo "✓ Cleaned."

# ══════════════════════════════════════════════════════════════════
#  ARCHIVE (external drive — F: /mnt/f/helios-archive)
# ══════════════════════════════════════════════════════════════════

archive-raw: ## Sync raw parquet to external drive
	@echo "═══ Archiving raw parquet → $(ARCHIVE_DIR)/staging/raw/ ═══"
	@mkdir -p $(ARCHIVE_DIR)/staging/raw/landsat
	rsync -av $(STAGING_DIR)/raw/landsat/*.parquet $(ARCHIVE_DIR)/staging/raw/landsat/
	rsync -av $(STAGING_DIR)/raw/zoning.geojson $(ARCHIVE_DIR)/staging/raw/ 2>/dev/null || true
	@echo "✓ Raw archived."

archive-dense: ## Sync dense matrices to external drive
	@echo "═══ Archiving dense matrix → $(ARCHIVE_DIR)/staging/helios_output/ ═══"
	@mkdir -p $(ARCHIVE_DIR)/staging/helios_output
	rsync -av $(STAGING_DIR)/helios_output/ $(ARCHIVE_DIR)/staging/helios_output/
	@echo "✓ Dense archived."

archive-reports: ## Sync ML reports to external drive
	@echo "═══ Archiving reports → $(ARCHIVE_DIR)/reports/ ═══"
	@mkdir -p $(ARCHIVE_DIR)/reports
	rsync -av $(PY_DIR)/reports/ $(ARCHIVE_DIR)/reports/
	@echo "✓ Reports archived."

archive: archive-raw archive-dense archive-reports ## Sync all validated data to external drive
	@echo "════════════════════════════════════════"
	@echo "  Archive sync complete."
	@echo "  Target: $(ARCHIVE_DIR)"
	@echo "════════════════════════════════════════"

sync-check: ## Verify archive matches local staging (dry-run rsync)
	@echo "═══ Checking archive sync status ═══"
	@rsync -avn $(STAGING_DIR)/raw/landsat/*.parquet $(ARCHIVE_DIR)/staging/raw/landsat/ 2>&1 | tail -5
	@rsync -avn $(STAGING_DIR)/helios_output/ $(ARCHIVE_DIR)/staging/helios_output/ 2>&1 | tail -5
	@echo "═══ Archive disk usage ═══"
	@du -sh $(ARCHIVE_DIR) 2>/dev/null || echo "Archive dir not found"
