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

# ── Ensure staging dirs exist ─────────────────────────────────────
$(STAGING_DIR)/raw $(STAGING_DIR)/dense:
	@mkdir -p $@

.PHONY: help setup setup-go setup-scala setup-python \
        ingest process train all clean lint test

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
