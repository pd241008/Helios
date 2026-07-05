package worker

import (
	"context"
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

type Task struct {
	Kind       string
	ID         string
	SourceURL  string
	Band       string
	Timestamp  int64
	CloudCover float64
}

type Stats struct {
	Succeeded int64
	Failed    int64
	TotalBytes int64
}

type Pool struct {
	workers   int
	outputDir string
	logger    *slog.Logger
}

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

func (p *Pool) Run(ctx context.Context, tasks []Task) (Stats, error) {
	var stats Stats
	taskCh := make(chan Task, len(tasks))
	var wg sync.WaitGroup

	for _, t := range tasks {
		taskCh <- t
	}
	close(taskCh)

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

func (p *Pool) runWorker(ctx context.Context, id int, ch <-chan Task, stats *Stats) {
	for {
		select {
		case <-ctx.Done():
			p.logger.Warn("worker shutting down", "worker", id, "reason", ctx.Err())
			return
		case task, ok := <-ch:
			if !ok {
				return
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

func (p *Pool) processTask(ctx context.Context, workerID int, task Task, stats *Stats) error {
	start := time.Now()
	p.logger.Info("processing",
		"worker", workerID,
		"task", task.ID,
		"kind", task.Kind,
	)

	raw, err := fetcher.Fetch(ctx, task.SourceURL)
	if err != nil {
		return fmt.Errorf("fetch %s: %w", task.ID, err)
	}
	atomic.AddInt64(&stats.TotalBytes, int64(len(raw)))

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

func writeParquet(path string, records []parser.Record) error {
	f, err := os.Create(path)
	if err != nil {
		return err
	}
	defer f.Close()

	header := fmt.Sprintf("PAR1-STUB records=%d\n", len(records))
	_, err = f.WriteString(header)
	return err
}
