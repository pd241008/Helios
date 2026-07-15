package main

import (
	"encoding/json"
	"fmt"
	"log/slog"
	"os"
	"path/filepath"
	"time"

	"github.com/helios/ingestion/internal/parser"
)

type sceneMeta struct {
	AcquisitionDatetime string `json:"acquisition_datetime"`
}

func main() {
	if len(os.Args) < 2 {
		fmt.Fprintf(os.Stderr, "usage: reprocess <landsat-dir> [scene-id ...]\n")
		os.Exit(1)
	}
	landsatDir := os.Args[1]
	logger := slog.New(slog.NewJSONHandler(os.Stdout, &slog.HandlerOptions{Level: slog.LevelInfo}))
	slog.SetDefault(logger)

	var scenes []string
	if len(os.Args) > 2 {
		scenes = os.Args[2:]
	} else {
		entries, err := os.ReadDir(landsatDir)
		if err != nil {
			slog.Error("cannot read landsat dir", "error", err)
			os.Exit(1)
		}
		for _, e := range entries {
			if e.IsDir() {
				scenes = append(scenes, e.Name())
			}
		}
	}

	for _, sceneID := range scenes {
		sceneDir := filepath.Join(landsatDir, sceneID)
		parquetPath := filepath.Join(landsatDir, sceneID+".parquet")

		// Read datetime from scene metadata if available.
		var ts time.Time
		metaPath := filepath.Join(sceneDir, "scene_metadata.json")
		if data, err := os.ReadFile(metaPath); err == nil {
			var m sceneMeta
			if json.Unmarshal(data, &m) == nil && m.AcquisitionDatetime != "" {
				ts, _ = time.Parse(time.RFC3339, m.AcquisitionDatetime)
			}
		}

		slog.Info("reprocessing scene", "scene", sceneID, "ts", ts)

		parsed := parser.NewGeoTIFFParser(sceneID, sceneDir, ts)
		sw, err := parser.NewParquetStreamWriter(parquetPath)
		if err != nil {
			slog.Error("create writer failed", "scene", sceneID, "error", err)
			continue
		}
		count, err := parsed.WriteStreaming(sw)
		if closeErr := sw.Close(); closeErr != nil {
			slog.Error("parquet close failed", "scene", sceneID, "error", closeErr)
		}
		if err != nil {
			slog.Error("parse failed", "scene", sceneID, "error", err)
			continue
		}
		slog.Info("scene reprocessed", "scene", sceneID, "records", count)
	}
}
