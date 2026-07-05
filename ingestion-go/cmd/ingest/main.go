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

	"github.com/helios/ingestion/internal/config"
	"github.com/helios/ingestion/internal/fetcher"
	"github.com/helios/ingestion/internal/worker"
)

func main() {
	outputDir := flag.String("output-dir", "./staging/raw", "Directory for raw parquet output")
	numWorkers := flag.Int("workers", 8, "Number of concurrent download workers")
	stacURL := flag.String("stac-url", "https://landsatlook.usgs.gov/stac-server", "STAC API base URL")
	bbox := flag.String("bbox", "80.0,12.8,80.4,13.2", "Bounding box: min_lon,min_lat,max_lon,max_lat")
	startYear := flag.Int("start-year", 2014, "Start year for scene search")
	endYear := flag.Int("end-year", 2023, "End year for scene search")
	maxCloud := flag.Float64("max-cloud", 10, "Maximum cloud cover percentage")
	flag.Parse()

	logger := slog.New(slog.NewJSONHandler(os.Stdout, &slog.HandlerOptions{Level: slog.LevelInfo}))
	slog.SetDefault(logger)

	ctx, cancel := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer cancel()

	absOut, err := filepath.Abs(*outputDir)
	if err != nil {
		slog.Error("invalid output path", "error", err)
		os.Exit(1)
	}
	if err := os.MkdirAll(absOut, 0o750); err != nil {
		slog.Error("cannot create output dir", "path", absOut, "error", err)
		os.Exit(1)
	}

	parsedBBox, err := config.ParseBBox(*bbox)
	if err != nil {
		slog.Error("invalid bbox", "error", err)
		os.Exit(1)
	}

	landsatCfg := config.LandsatConfig{
		STACURL:   *stacURL,
		BBox:      parsedBBox,
		StartYear: *startYear,
		EndYear:   *endYear,
		MaxCloud:  *maxCloud,
	}

	slog.Info("discovering Landsat scenes",
		"stac_url", landsatCfg.STACURL,
		"bbox", landsatCfg.BBox,
		"years", fmt.Sprintf("%d-%d", landsatCfg.StartYear, landsatCfg.EndYear),
		"max_cloud", landsatCfg.MaxCloud,
	)

	assets, err := fetcher.DiscoverScenes(ctx, landsatCfg)
	if err != nil {
		slog.Error("scene discovery failed", "error", err)
		os.Exit(1)
	}

	var tasks []worker.Task
	if len(assets) > 0 {
		for _, a := range assets {
			tasks = append(tasks, worker.Task{
				Kind:       "landsat",
				ID:         a.SceneID + "_" + a.BandKey,
				SourceURL:  a.DownloadURL,
				Band:       a.BandName,
				Timestamp:  a.Timestamp,
				CloudCover: a.CloudCover,
			})
		}
	} else {
		slog.Warn("no Landsat scenes found, falling back to demo manifest",
			"bbox", *bbox, "cloud_max", *maxCloud)
		tasks = buildDemoManifest()
	}

	slog.Info("starting ingestion",
		"workers", *numWorkers,
		"tasks", len(tasks),
		"output", absOut,
	)

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

func buildDemoManifest() []worker.Task {
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
	fmt.Fprintln(os.Stderr, "helios/ingestion — concurrent Landsat & OSM fetcher")
}
