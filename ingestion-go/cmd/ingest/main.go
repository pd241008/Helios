package main

import (
	"context"
	"flag"
	"fmt"
	"log/slog"
	"os"
	"os/signal"
	"path/filepath"
	"strings"
	"syscall"
	"time"

	"github.com/helios/ingestion/internal/config"
	"github.com/helios/ingestion/internal/fetcher"
	"github.com/helios/ingestion/internal/parser"
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
	fetchSplitWindow := flag.Bool("fetch-split-window", false, "Fetch TOA B10/B11 for split-window LST")
	lulcShapefile := flag.String("lulc-shapefile", "", "Path to .shp shapefile for LULC features")
	lulcGeoJSON := flag.String("lulc-geojson", "", "Path to .geojson file for LULC features")
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

	cfg := config.Config{
		STACURL:          *stacURL,
		BBox:             parsedBBox,
		StartYear:        *startYear,
		EndYear:          *endYear,
		MaxCloud:         *maxCloud,
		FetchSplitWindow: *fetchSplitWindow,
		Workers:          *numWorkers,
		RetryAttempts:    3,
		RetryBackoff:     500 * time.Millisecond,
		StagingDir:       absOut,
	}

	// ── Phase 1.2: Vector data processing (Shapefile / GeoJSON) ──
	vectorOut := filepath.Join(absOut, "lulc")
	if *lulcShapefile != "" {
		if err := processShapefile(ctx, *lulcShapefile, vectorOut); err != nil {
			slog.Error("shapefile processing failed", "error", err)
			os.Exit(1)
		}
	}
	if *lulcGeoJSON != "" {
		if err := processGeoJSON(ctx, *lulcGeoJSON, vectorOut); err != nil {
			slog.Error("geojson processing failed", "error", err)
			os.Exit(1)
		}
	}

	if cfg.FetchSplitWindow {
		slog.Info("discovering split-window scenes",
			"stac_url", cfg.STACURL,
			"bbox", cfg.BBox,
			"years", fmt.Sprintf("%d-%d", cfg.StartYear, cfg.EndYear),
			"max_cloud", cfg.MaxCloud,
			"collection_l2", cfg.CollectionL2,
			"collection_toa", cfg.CollectionTOA,
		)

		scenes, err := fetcher.DiscoverSplitWindowScenes(ctx, cfg)
		if err != nil {
			slog.Error("scene discovery failed", "error", err)
			os.Exit(1)
		}

		var sceneTasks []worker.SceneTask
		for _, s := range scenes {
			sceneTasks = append(sceneTasks, worker.SceneTask{
				SceneID:    s.SceneID,
				DateTime:   s.DateTime,
				CloudCover: s.CloudCover,
				WRSPath:    s.WRSPath,
				WRSRow:     s.WRSRow,
				BandURLs:   s.Assets,
				K1Band10:   s.K1Band10,
				K2Band10:   s.K2Band10,
				K1Band11:   s.K1Band11,
				K2Band11:   s.K2Band11,
			})
		}

		slog.Info("starting split-window ingestion",
			"workers", *numWorkers,
			"scenes", len(sceneTasks),
			"output", absOut,
		)

		pool := worker.NewPoolWithRetry(*numWorkers, absOut, cfg.RetryAttempts, cfg.RetryBackoff, logger)
		sceneStats, err := pool.RunScenes(ctx, sceneTasks)
		if err != nil {
			slog.Error("ingestion failed", "error", err)
			os.Exit(1)
		}

		slog.Info("ingestion complete",
			"scenes_succeeded", sceneStats.ScenesSucceeded,
			"scenes_failed", sceneStats.ScenesFailed,
			"bands_downloaded", sceneStats.BandsDownloaded,
			"total_bytes", sceneStats.TotalBytes,
		)
		return
	}

	// Legacy single-collection L2 flow.
	slog.Info("discovering Landsat scenes",
		"stac_url", cfg.STACURL,
		"bbox", cfg.BBox,
		"years", fmt.Sprintf("%d-%d", cfg.StartYear, cfg.EndYear),
		"max_cloud", cfg.MaxCloud,
	)

	assets, err := fetcher.DiscoverScenes(ctx, cfg)
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

func processShapefile(ctx context.Context, shpPath, outputDir string) error {
	slog.Info("processing shapefile", "path", shpPath, "output", outputDir)

	records, err := parser.ParseShapefile(shpPath, filepath.Base(shpPath))
	if err != nil {
		return fmt.Errorf("parse shapefile: %w", err)
	}
	slog.Info("parsed shapefile", "features", len(records))

	outPath := filepath.Join(outputDir, strings.TrimSuffix(filepath.Base(shpPath), ".shp")+".parquet")
	if err := parser.WriteRecords(outPath, records); err != nil {
		return fmt.Errorf("write parquet: %w", err)
	}
	slog.Info("wrote lulc parquet", "path", outPath, "records", len(records))
	return nil
}

func processGeoJSON(ctx context.Context, geojsonPath, outputDir string) error {
	slog.Info("processing geojson", "path", geojsonPath, "output", outputDir)

	data, err := os.ReadFile(geojsonPath)
	if err != nil {
		return fmt.Errorf("read geojson: %w", err)
	}

	sourceID := strings.TrimSuffix(filepath.Base(geojsonPath), ".geojson")
	records, err := parser.ParseGeoJSON(data, sourceID)
	if err != nil {
		return fmt.Errorf("parse geojson: %w", err)
	}
	slog.Info("parsed geojson", "features", len(records))

	outPath := filepath.Join(outputDir, sourceID+".parquet")
	if err := parser.WriteRecords(outPath, records); err != nil {
		return fmt.Errorf("write parquet: %w", err)
	}
	slog.Info("wrote lulc parquet", "path", outPath, "records", len(records))
	return nil
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
