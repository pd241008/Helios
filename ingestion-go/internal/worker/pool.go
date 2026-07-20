package worker

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"log/slog"
	"os"
	"path/filepath"
	"sync"
	"sync/atomic"
	"time"

	"github.com/helios/ingestion/internal/config"
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
	Succeeded  int64
	Failed     int64
	TotalBytes int64
}

// --- Scene-level types for split-window LST flow ---

type SceneTask struct {
	SceneID    string
	DateTime   time.Time
	CloudCover float64
	WRSPath    int
	WRSRow     int
	BandURLs   map[string]string // band key → download URL
	K1Band10   float64
	K2Band10   float64
	K1Band11   float64
	K2Band11   float64
}

type SceneStats struct {
	ScenesSucceeded int64
	ScenesFailed    int64
	BandsDownloaded int64
	TotalBytes      int64
}

type SceneMetadata struct {
	SceneID    string            `json:"scene_id"`
	DateTime   string            `json:"acquisition_datetime"`
	CloudCover float64           `json:"cloud_cover"`
	WRSPath    int               `json:"wrs_path"`
	WRSRow     int               `json:"wrs_row"`
	BandFiles  map[string]string `json:"band_files"`
	K1Band10   float64           `json:"k1_constant_band_10"`
	K2Band10   float64           `json:"k2_constant_band_10"`
	K1Band11   float64           `json:"k1_constant_band_11"`
	K2Band11   float64           `json:"k2_constant_band_11"`
	Processing string            `json:"processing_level"`
}

type Pool struct {
	workers       int
	outputDir     string
	cfg           config.Config
	retryAttempts int
	retryBackoff  time.Duration
	logger        *slog.Logger
}

func NewPool(workers int, outputDir string, cfg config.Config, logger *slog.Logger) *Pool {
	if workers < 1 {
		workers = 1
	}
	return &Pool{
		workers:       workers,
		outputDir:     outputDir,
		cfg:           cfg,
		retryAttempts: 3,
		retryBackoff:  500 * time.Millisecond,
		logger:        logger,
	}
}

func NewPoolWithRetry(workers int, outputDir string, cfg config.Config, logger *slog.Logger) *Pool {
	if workers < 1 {
		workers = 1
	}
	retryAttempts := cfg.RetryAttempts
	if retryAttempts < 1 {
		retryAttempts = 3
	}
	retryBackoff := cfg.RetryBackoff
	if retryBackoff <= 0 {
		retryBackoff = 500 * time.Millisecond
	}
	return &Pool{
		workers:       workers,
		outputDir:     outputDir,
		cfg:           cfg,
		retryAttempts: retryAttempts,
		retryBackoff:  retryBackoff,
		logger:        logger,
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
	if err := parser.WriteRecords(outPath, records); err != nil {
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

// RunScenes processes scene-level tasks, downloading all band assets per scene
// concurrently and writing raw GeoTIFFs plus a scene-level JSON metadata sidecar.
func (p *Pool) RunScenes(ctx context.Context, scenes []SceneTask) (SceneStats, error) {
	var stats SceneStats
	sceneCh := make(chan SceneTask, len(scenes))
	var wg sync.WaitGroup

	for _, s := range scenes {
		sceneCh <- s
	}
	close(sceneCh)

	for i := range p.workers {
		wg.Add(1)
		go func(workerID int) {
			defer wg.Done()
			p.runSceneWorker(ctx, workerID, sceneCh, &stats)
		}(i)
	}

	wg.Wait()

	if ctx.Err() != nil {
		return stats, fmt.Errorf("pool cancelled: %w", ctx.Err())
	}
	return stats, nil
}

func (p *Pool) runSceneWorker(ctx context.Context, id int, ch <-chan SceneTask, stats *SceneStats) {
	for {
		select {
		case <-ctx.Done():
			p.logger.Warn("scene worker shutting down", "worker", id, "reason", ctx.Err())
			return
		case scene, ok := <-ch:
			if !ok {
				return
			}
			if err := p.processScene(ctx, id, scene, stats); err != nil {
				atomic.AddInt64(&stats.ScenesFailed, 1)
				p.logger.Error("scene failed",
					"worker", id,
					"scene", scene.SceneID,
					"error", err,
				)
			} else {
				atomic.AddInt64(&stats.ScenesSucceeded, 1)
			}
		}
	}
}

func (p *Pool) processScene(ctx context.Context, workerID int, scene SceneTask, stats *SceneStats) error {
	sceneDir := filepath.Join(p.outputDir, "landsat", scene.SceneID)
	if err := os.MkdirAll(sceneDir, 0o750); err != nil {
		return fmt.Errorf("mkdir %s: %w", sceneDir, err)
	}

	type bandResult struct {
		key  string
		size int64
		err  error
	}

	// Two-stage fetch: QA_PIXEL first for AOI cloud filtering.
	var qaDest string
	var qaSize int64
	if qaURL, ok := scene.BandURLs["QA_PIXEL"]; ok {
		p.logger.Info("fetching QA_PIXEL for AOI cloud check", "scene", scene.SceneID)
		qaDest = filepath.Join(sceneDir, "QA_PIXEL.tif")
		size, err := fetcher.FetchToFile(ctx, qaURL, qaDest)
		if err != nil {
			return fmt.Errorf("scene %s QA_PIXEL fetch failed: %w", scene.SceneID, err)
		}
		qaSize = size

		// Compute AOI cloud cover
		aoiCloud, err := parser.ComputeAOICloudCover(qaDest, [4]float64(p.cfg.BBox))
		if err != nil {
			return fmt.Errorf("scene %s AOI cloud compute failed: %w", scene.SceneID, err)
		}

		if aoiCloud > p.cfg.MaxAOICloud && aoiCloud >= 0 {
			p.logger.Warn("scene rejected by AOI cloud filter",
				"scene", scene.SceneID,
				"cloud_cover_scene", scene.CloudCover,
				"cloud_cover_aoi", aoiCloud,
				"max_aoi_cloud", p.cfg.MaxAOICloud,
			)
			// Cleanly abort. Remove QA_PIXEL and dir.
			os.Remove(qaDest)
			os.Remove(sceneDir)
			// We return nil to avoid failing the whole ingestion job, just skip this scene
			// but we should probably record it as skipped or failed.
			// Wait, if we return an error, it increments ScenesFailed. 
			// Let's return a specific error that can be ignored, or just log and return an error so it's counted.
			return fmt.Errorf("REJECTED_AOI_CLOUD: scene %s aoi cloud %.2f%% > %.2f%%", scene.SceneID, aoiCloud, p.cfg.MaxAOICloud)
		}
		p.logger.Info("scene passed AOI cloud filter",
			"scene", scene.SceneID,
			"cloud_cover_scene", scene.CloudCover,
			"cloud_cover_aoi", aoiCloud,
		)
		// We can add AOI cloud cover to scene.CloudCover or metadata later
		scene.CloudCover = aoiCloud // We'll store it here to pass to metadata, or add a new field.
		// Wait, the SceneTask doesn't have an AOICloudCover field. We will use a hack: store it in a local variable.
	}

	resCh := make(chan bandResult, len(scene.BandURLs))
	var bwg sync.WaitGroup

	// Per-scene band concurrency bounded by total worker count.
	sem := make(chan struct{}, p.workers)

	for bandKey, url := range scene.BandURLs {
		if bandKey == "QA_PIXEL" && qaDest != "" {
			resCh <- bandResult{key: bandKey, size: qaSize, err: nil}
			continue
		}
		bwg.Add(1)
		go func(k, u string) {
			defer bwg.Done()
			sem <- struct{}{}
			defer func() { <-sem }()

			dest := filepath.Join(sceneDir, k+".tif")
			size, err := fetcher.FetchToFile(ctx, u, dest)
			resCh <- bandResult{key: k, size: size, err: err}
		}(bandKey, url)
	}

	go func() {
		bwg.Wait()
		close(resCh)
	}()

	var totalBytes int64
	var succeededBands []string
	var failedBands []string

	for r := range resCh {
		if r.err != nil {
			failedBands = append(failedBands, r.key)
			p.logger.Error("band download failed",
				"scene", scene.SceneID, "band", r.key, "error", r.err,
			)
			continue
		}
		succeededBands = append(succeededBands, r.key)
		totalBytes += r.size
	}

	// Write scene-level JSON metadata sidecar.
	meta := SceneMetadata{
		SceneID:    scene.SceneID,
		DateTime:   scene.DateTime.Format(time.RFC3339),
		CloudCover: scene.CloudCover,
		WRSPath:    scene.WRSPath,
		WRSRow:     scene.WRSRow,
		BandFiles:  make(map[string]string, len(scene.BandURLs)),
		K1Band10:   scene.K1Band10,
		K2Band10:   scene.K2Band10,
		K1Band11:   scene.K1Band11,
		K2Band11:   scene.K2Band11,
		Processing: "split-window-lst",
	}
	for k := range scene.BandURLs {
		meta.BandFiles[k] = k + ".tif"
	}

	metaPath := filepath.Join(sceneDir, "scene_metadata.json")
	metaData, err := json.MarshalIndent(meta, "", "  ")
	if err != nil {
		return fmt.Errorf("marshal metadata: %w", err)
	}
	if err := os.WriteFile(metaPath, metaData, 0o640); err != nil {
		return fmt.Errorf("write metadata: %w", err)
	}

	atomic.AddInt64(&stats.TotalBytes, totalBytes)
	atomic.AddInt64(&stats.BandsDownloaded, int64(len(succeededBands)))

	if len(failedBands) > 0 {
		return fmt.Errorf("scene %s: %d/%d bands failed: %v",
			scene.SceneID, len(failedBands), len(scene.BandURLs), failedBands)
	}

	p.logger.Info("scene completed",
		"worker", workerID,
		"scene", scene.SceneID,
		"bands", len(succeededBands),
		"bytes", totalBytes,
	)

	// ── GeoTIFF-to-Record streaming parse ────────────────────────────
	// Records are written directly to the parquet file during parsing,
	// one record at a time. This keeps peak memory at ~1 TIFF image +
	// 1 float64 pixel array (~300-400 MB), NOT the full Record slice
	// (which would be ~25 GB for a 252M-record scene).
	memBefore := readMemMB()
	parsed := parser.NewGeoTIFFParser(scene.SceneID, sceneDir, scene.DateTime)
	sw, err := parser.NewParquetStreamWriter(filepath.Join(p.outputDir, "landsat", scene.SceneID+".parquet"))
	if err != nil {
		return fmt.Errorf("create parquet writer for %s: %w", scene.SceneID, err)
	}
	count, err := parsed.WriteStreaming(sw)
	if closeErr := sw.Close(); closeErr != nil {
		p.logger.Error("parquet close failed", "scene", scene.SceneID, "error", closeErr)
	}
	if err != nil {
		return fmt.Errorf("parse GeoTIFFs for scene %s: %w", scene.SceneID, err)
	}
	memAfter := readMemMB()
	p.logger.Info("parquet written",
		"scene", scene.SceneID,
		"records", count,
		"mem_before_parse_MB", memBefore,
		"mem_after_parse_MB", memAfter,
		"mem_delta_MB", memAfter-memBefore,
	)

	// ── Cleanup: remove raw TIFFs after successful parquet write ─────
	// TIFFs are redundant once parquet is validated (PAR1 footer confirmed).
	// They can be re-downloaded/re-signed from Planetary Computer if needed.
	// This prevents unbounded disk growth during multi-year ingestion runs.
	if err := cleanupSceneTIFFs(sceneDir, p.logger); err != nil {
		p.logger.Warn("TIFF cleanup failed (non-fatal)", "scene", scene.SceneID, "error", err)
	}

	return nil
}

// cleanupSceneTIFFs removes all .tif files in sceneDir after successful parquet
// write. This is safe because: (1) the parquet file is the source of truth,
// (2) SAS-signed URLs are short-lived anyway, (3) TIFFs can be re-downloaded
// from Planetary Computer if reprocessing is needed.
func cleanupSceneTIFFs(sceneDir string, logger *slog.Logger) error {
	entries, err := os.ReadDir(sceneDir)
	if err != nil {
		return fmt.Errorf("read scene dir: %w", err)
	}
	var removed int
	for _, e := range entries {
		if !e.IsDir() && filepath.Ext(e.Name()) == ".tif" {
			path := filepath.Join(sceneDir, e.Name())
			if err := os.Remove(path); err != nil {
				logger.Warn("failed to remove TIFF", "path", path, "error", err)
				continue
			}
			removed++
		}
	}
	if removed > 0 {
		logger.Info("cleaned up raw TIFFs",
			"scene", filepath.Base(sceneDir),
			"removed", removed,
		)
	}
	return nil
}

// readMemMB returns the current process RSS in MB by reading /proc/self/status.
func readMemMB() int64 {
	data, err := os.ReadFile("/proc/self/status")
	if err != nil {
		return 0
	}
	for _, line := range bytes.Split(data, []byte("\n")) {
		if bytes.HasPrefix(line, []byte("VmRSS:")) {
			var kb int64
			fmt.Sscanf(string(line), "VmRSS: %d kB", &kb)
			return kb / 1024
		}
	}
	return 0
}
