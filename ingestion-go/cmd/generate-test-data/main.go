package main

import (
	"encoding/json"
	"fmt"
	"log"
	"os"
	"path/filepath"

	"github.com/helios/ingestion/internal/parser"
)

func main() {
	outDir := "./staging/raw"
	if len(os.Args) > 1 {
		outDir = os.Args[1]
	}
	absOut, err := filepath.Abs(outDir)
	if err != nil {
		log.Fatal(err)
	}

	sceneIDs := []string{
		"LC08_L2SP_044034_20240301",
		"LC08_L2SP_044035_20240301",
		"LC08_L2SP_045034_20240301",
		"LC08_L2SP_045035_20240301",
	}

	// Generate Landsat Parquet files + metadata sidecars
	for _, sid := range sceneIDs {
		raw := make([]byte, 8)
		records, err := parser.ParseGeoTIFF(raw, sid)
		if err != nil {
			log.Fatalf("ParseGeoTIFF: %v", err)
		}

		parquetDir := filepath.Join(absOut, "landsat")
		if err := os.MkdirAll(parquetDir, 0o750); err != nil {
			log.Fatal(err)
		}

		parquetPath := filepath.Join(parquetDir, sid+".parquet")
		if err := parser.WriteRecords(parquetPath, records); err != nil {
			log.Fatalf("WriteRecords: %v", err)
		}
		fmt.Printf("  ✓ %s\n", parquetPath)

		sceneDir := filepath.Join(parquetDir, sid)
		if err := os.MkdirAll(sceneDir, 0o750); err != nil {
			log.Fatal(err)
		}
		writeSceneMetadata(sceneDir, sid)
	}

	// Generate GeoJSON for LULC zoning
	geojsonDir := filepath.Join(absOut, "lulc")
	if err := os.MkdirAll(geojsonDir, 0o750); err != nil {
		log.Fatal(err)
	}
	geojsonPath := filepath.Join(geojsonDir, "zoning.geojson")
	writeGeoJSON(geojsonPath)

	fmt.Println("Test data generated successfully")
}

func writeSceneMetadata(dir, sceneID string) {
	meta := map[string]any{
		"scene_id":              sceneID,
		"acquisition_datetime":  "2024-03-01T10:30:00Z",
		"cloud_cover":           2.5,
		"wrs_path":              44,
		"wrs_row":               34,
		"band_files":            map[string]string{},
		"k1_constant_band_10":   774.8853,
		"k2_constant_band_10":   1321.0789,
		"k1_constant_band_11":   480.8883,
		"k2_constant_band_11":   1201.1442,
		"processing_level":      "split-window-lst",
	}
	data, err := json.MarshalIndent(meta, "", "  ")
	if err != nil {
		log.Fatalf("marshal meta: %v", err)
	}
	path := filepath.Join(dir, "scene_metadata.json")
	if err := os.WriteFile(path, data, 0o640); err != nil {
		log.Fatalf("write meta: %v", err)
	}
	fmt.Printf("  ✓ %s\n", path)
}

func writeGeoJSON(path string) {
	fc := map[string]any{
		"type": "FeatureCollection",
		"features": []map[string]any{
			{
				"type": "Feature",
				"properties": map[string]string{
					"zoning_category": "residential",
				},
				"geometry": map[string]any{
					"type": "Polygon",
					"coordinates": [][][]float64{
						{
							{-118.5, 33.5},
							{-117.5, 33.5},
							{-117.5, 34.5},
							{-118.5, 34.5},
							{-118.5, 33.5},
						},
					},
				},
			},
			{
				"type": "Feature",
				"properties": map[string]string{
					"zoning_category": "agricultural",
				},
				"geometry": map[string]any{
					"type": "Polygon",
					"coordinates": [][][]float64{
						{
							{-118.5, 34.5},
							{-117.5, 34.5},
							{-117.5, 35.5},
							{-118.5, 35.5},
							{-118.5, 34.5},
						},
					},
				},
			},
			{
				"type": "Feature",
				"properties": map[string]string{
					"zoning_category": "commercial",
				},
				"geometry": map[string]any{
					"type": "Polygon",
					"coordinates": [][][]float64{
						{
							{-119.5, 33.5},
							{-118.5, 33.5},
							{-118.5, 34.5},
							{-119.5, 34.5},
							{-119.5, 33.5},
						},
					},
				},
			},
		},
	}

	data, err := json.MarshalIndent(fc, "", "  ")
	if err != nil {
		log.Fatalf("marshal geojson: %v", err)
	}
	if err := os.WriteFile(path, data, 0o640); err != nil {
		log.Fatalf("write geojson: %v", err)
	}
	fmt.Printf("  ✓ %s\n", path)

}
