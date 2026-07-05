// Package main is the entry-point for the Helios ingestion pipeline.
//
// It launches a bounded worker pool of goroutines that concurrently:
//  1. Fetch Landsat GeoTIFF tiles from a remote catalog.
//  2. Parse raw OpenStreetMap (OSM) spatial shards.
//  3. Serialize cleaned records into partitioned Parquet files
//     under the staging directory.
//
// Usage:
//
//	go run ./cmd/ingest --output-dir ./staging/raw --workers 8
package main

import (
	"context"
	"flag"
	"fmt"
	"log/slog"
	"os"
	"os/signal"
	"path/filepath"
	"syscall"

	"github.com/helios/ingestion/internal/worker"
)

func main() {
	// ── CLI flags ────────────────────────────────────────────────────
	outputDir := flag.String("output-dir", "./staging/raw", "Directory for raw parquet output")
	numWorkers := flag.Int("workers", 8, "Number of concurrent download workers")
	flag.Parse()

	// ── Logger ───────────────────────────────────────────────────────
	logger := slog.New(slog.NewJSONHandler(os.Stdout, &slog.HandlerOptions{Level: slog.LevelInfo}))
	slog.SetDefault(logger)

	// ── Graceful shutdown ────────────────────────────────────────────
	ctx, cancel := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer cancel()

	// ── Ensure output directory exists ───────────────────────────────
	absOut, err := filepath.Abs(*outputDir)
	if err != nil {
		slog.Error("invalid output path", "error", err)
		os.Exit(1)
	}
	if err := os.MkdirAll(absOut, 0o750); err != nil {
		slog.Error("cannot create output dir", "path", absOut, "error", err)
		os.Exit(1)
	}

	// ── Build work manifest ──────────────────────────────────────────
	// In production this would come from a tile index API or a local
	// manifest file. Here we generate synthetic task descriptors.
	tasks := buildDemoManifest()

	slog.Info("starting ingestion",
		"workers", *numWorkers,
		"tasks", len(tasks),
		"output", absOut,
	)

	// ── Launch pool ──────────────────────────────────────────────────
	pool := worker.NewPool(*numWorkers, absOut, logger)
	stats, err := pool.Run(ctx, tasks)
	if err != nil {
		slog.Error("ingestion failed", "error", err)
		os.Exit(1)
	}

	slog.Info("ingestion complete",
		"succeeded", stats.Succeeded,
		"failed", stats.Failed,
		"total_bytes", stats.TotalBytes,
	)
}

// buildDemoManifest returns synthetic tile descriptors for demonstration.
// Replace with a real catalog reader (e.g., STAC API client) in production.
func buildDemoManifest() []worker.Task {
	// Simulated Landsat WRS-2 path/row tiles + OSM region shards
	tiles := []struct {
		kind string
		id   string
		url  string
	}{
		{"landsat", "LC08_L2SP_044034_20240301", "https://landsat-catalog.example.com/tiles/044034_20240301.tif"},
		{"landsat", "LC08_L2SP_044035_20240301", "https://landsat-catalog.example.com/tiles/044035_20240301.tif"},
		{"landsat", "LC08_L2SP_045034_20240301", "https://landsat-catalog.example.com/tiles/045034_20240301.tif"},
		{"landsat", "LC08_L2SP_045035_20240301", "https://landsat-catalog.example.com/tiles/045035_20240301.tif"},
		{"landsat", "LC08_L2SP_046034_20240301", "https://landsat-catalog.example.com/tiles/046034_20240301.tif"},
		{"landsat", "LC08_L2SP_046035_20240301", "https://landsat-catalog.example.com/tiles/046035_20240301.tif"},
		{"osm", "region_north_34", "https://osm-extracts.example.com/shards/north_34.osm.pbf"},
		{"osm", "region_north_35", "https://osm-extracts.example.com/shards/north_35.osm.pbf"},
		{"osm", "region_south_34", "https://osm-extracts.example.com/shards/south_34.osm.pbf"},
		{"osm", "region_south_35", "https://osm-extracts.example.com/shards/south_35.osm.pbf"},
	}

	tasks := make([]worker.Task, 0, len(tiles))
	for _, t := range tiles {
		tasks = append(tasks, worker.Task{
			Kind:     t.kind,
			ID:       t.id,
			SourceURL: t.url,
		})
	}
	return tasks
}

func init() {
	fmt.Fprintln(os.Stderr, "helios/ingestion — concurrent GeoTIFF & OSM fetcher")
}
