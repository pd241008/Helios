// Package worker implements a bounded goroutine pool for concurrent
// data ingestion. Each worker picks tasks from a shared channel,
// fetches the remote resource, parses/cleans it, and writes partitioned
// Parquet output.
//
// The pool respects context cancellation for graceful shutdown and
// collects per-task error/success statistics.
package worker

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"fmt"
	"log/slog"
	"os"
	"path/filepath"
	"sync"
	"sync/atomic"
	"time"

	"github.com/helios/ingestion/internal/fetcher"
	"github.com/helios/ingestion/internal/parser"
)

// ── Types ────────────────────────────────────────────────────────────

// Task describes a single unit of work for the ingestion pipeline.
type Task struct {
	Kind      string // "landsat" or "osm"
	ID        string // Unique tile / shard identifier
	SourceURL string // Remote URL to fetch
}

// Stats holds aggregate counters for a completed pool run.
type Stats struct {
	Succeeded int64
	Failed    int64
	TotalBytes int64
}

// Pool is a bounded worker pool that processes ingestion Tasks
// concurrently using a fixed number of goroutines.
type Pool struct {
	workers   int
	outputDir string
	logger    *slog.Logger
}

// ── Constructor ──────────────────────────────────────────────────────

// NewPool creates a new worker pool. Workers will write Parquet output
// into outputDir, partitioned by task kind and ID.
func NewPool(workers int, outputDir string, logger *slog.Logger) *Pool {
	if workers < 1 {
		workers = 1
	}
	return &Pool{
		workers:   workers,
		outputDir: outputDir,
		logger:    logger,
	}
}

// ── Run ──────────────────────────────────────────────────────────────

// Run fans out tasks across the worker goroutines and blocks until all
// are complete or the context is cancelled. It returns aggregate stats.
func (p *Pool) Run(ctx context.Context, tasks []Task) (Stats, error) {
	var stats Stats
	taskCh := make(chan Task, len(tasks))
	var wg sync.WaitGroup

	// Enqueue all tasks.
	for _, t := range tasks {
		taskCh <- t
	}
	close(taskCh)

	// Spawn workers.
	for i := range p.workers {
		wg.Add(1)
		go func(workerID int) {
			defer wg.Done()
			p.runWorker(ctx, workerID, taskCh, &stats)
		}(i)
	}

	wg.Wait()

	if ctx.Err() != nil {
		return stats, fmt.Errorf("pool cancelled: %w", ctx.Err())
	}
	return stats, nil
}

// ── Worker loop ──────────────────────────────────────────────────────

func (p *Pool) runWorker(ctx context.Context, id int, ch <-chan Task, stats *Stats) {
	for {
		select {
		case <-ctx.Done():
			p.logger.Warn("worker shutting down", "worker", id, "reason", ctx.Err())
			return
		case task, ok := <-ch:
			if !ok {
				return // channel drained
			}
			if err := p.processTask(ctx, id, task, stats); err != nil {
				atomic.AddInt64(&stats.Failed, 1)
				p.logger.Error("task failed",
					"worker", id,
					"task", task.ID,
					"kind", task.Kind,
					"error", err,
				)
			} else {
				atomic.AddInt64(&stats.Succeeded, 1)
			}
		}
	}
}

// ── Single-task processing ───────────────────────────────────────────

func (p *Pool) processTask(ctx context.Context, workerID int, task Task, stats *Stats) error {
	start := time.Now()
	p.logger.Info("processing",
		"worker", workerID,
		"task", task.ID,
		"kind", task.Kind,
	)

	// 1. Fetch raw bytes from remote source.
	raw, err := fetcher.Fetch(ctx, task.SourceURL)
	if err != nil {
		return fmt.Errorf("fetch %s: %w", task.ID, err)
	}
	atomic.AddInt64(&stats.TotalBytes, int64(len(raw)))

	// 2. Parse and clean based on data kind.
	var records []parser.Record
	switch task.Kind {
	case "landsat":
		records, err = parser.ParseGeoTIFF(raw, task.ID)
	case "osm":
		records, err = parser.ParseOSMShard(raw, task.ID)
	default:
		return fmt.Errorf("unknown task kind: %q", task.Kind)
	}
	if err != nil {
		return fmt.Errorf("parse %s: %w", task.ID, err)
	}

	// 3. Write partitioned Parquet.
	outPath := filepath.Join(p.outputDir, task.Kind, task.ID+".parquet")
	if err := os.MkdirAll(filepath.Dir(outPath), 0o750); err != nil {
		return fmt.Errorf("mkdir %s: %w", filepath.Dir(outPath), err)
	}
	if err := writeParquet(outPath, records); err != nil {
		return fmt.Errorf("write parquet %s: %w", outPath, err)
	}

	p.logger.Info("completed",
		"worker", workerID,
		"task", task.ID,
		"records", len(records),
		"elapsed", time.Since(start).String(),
	)
	return nil
}

// ── Parquet writer (stub) ────────────────────────────────────────────

// writeParquet serializes records into a Parquet file. In production
// this uses parquet-go; here we write a placeholder to demonstrate the
// file-creation path without pulling the full dependency tree.
func writeParquet(path string, records []parser.Record) error {
	// TODO(production): Replace with real parquet-go writer.
	// Schema: tile_id string, lat float64, lon float64, band string,
	//         value float64, timestamp int64, lulc_class string
	f, err := os.Create(path)
	if err != nil {
		return err
	}
	defer f.Close()

	// Write a magic header so downstream readers can detect the format.
	header := fmt.Sprintf("PAR1-STUB records=%d\n", len(records))
	_, err = f.WriteString(header)
	return err
}

// secureRandomHex returns a cryptographically random hex string of n bytes.
// Useful for generating unique partition suffixes.
func secureRandomHex(n int) (string, error) {
	b := make([]byte, n)
	if _, err := rand.Read(b); err != nil {
		return "", err
	}
	return hex.EncodeToString(b), nil
}
