// Package parser converts raw byte payloads (GeoTIFF, OSM PBF) into
// a uniform slice of Record structs ready for Parquet serialization.
//
// In production, GeoTIFF parsing would use a GDAL binding or a pure-Go
// TIFF reader, and OSM parsing would use the osm package. Here we
// provide the structural scaffolding with synthetic records.
package parser

import (
	"crypto/sha256"
	"encoding/binary"
	"fmt"
	"math"
)

// Record is a single cleaned observation, ready for Parquet output.
// It represents one spatial pixel / feature with associated metadata.
type Record struct {
	TileID    string  `parquet:"name=tile_id, type=BYTE_ARRAY, convertedtype=UTF8"`
	Lat       float64 `parquet:"name=lat, type=DOUBLE"`
	Lon       float64 `parquet:"name=lon, type=DOUBLE"`
	Band      string  `parquet:"name=band, type=BYTE_ARRAY, convertedtype=UTF8"`
	Value     float64 `parquet:"name=value, type=DOUBLE"`
	Timestamp int64   `parquet:"name=timestamp, type=INT64, convertedtype=TIMESTAMP_MILLIS"`
	LULCClass string  `parquet:"name=lulc_class, type=BYTE_ARRAY, convertedtype=UTF8"`
}

// ParseGeoTIFF extracts pixel-level observations from a Landsat
// GeoTIFF payload. Each pixel becomes one Record with band reflectance
// or thermal values.
//
// TODO(production): Integrate with a real TIFF/GDAL reader.
func ParseGeoTIFF(raw []byte, tileID string) ([]Record, error) {
	if len(raw) < 8 {
		return nil, fmt.Errorf("geotiff payload too small (%d bytes)", len(raw))
	}

	// Derive deterministic synthetic records from the payload hash
	// so outputs are reproducible across runs.
	h := sha256.Sum256(raw)
	seed := binary.LittleEndian.Uint64(h[:8])

	bands := []string{"B2_Blue", "B3_Green", "B4_Red", "B5_NIR", "B6_SWIR1", "B10_TIR"}
	lulcClasses := []string{
		"urban", "forest", "cropland", "water", "barren",
		"grassland", "wetland", "shrubland", "snow_ice",
	}

	// Generate ~100 synthetic pixel records per tile.
	const pixelsPerTile = 100
	records := make([]Record, 0, pixelsPerTile*len(bands))

	for i := range pixelsPerTile {
		lat := 34.0 + float64(i)*0.01
		lon := -118.0 + float64(i)*0.01

		for bi, band := range bands {
			val := math.Sin(float64(seed)+float64(i)*0.1+float64(bi)) * 10000
			records = append(records, Record{
				TileID:    tileID,
				Lat:       lat,
				Lon:       lon,
				Band:      band,
				Value:     math.Round(val*100) / 100,
				Timestamp: 1709251200000 + int64(i*1000), // 2024-03-01 epoch millis
				LULCClass: lulcClasses[i%len(lulcClasses)],
			})
		}
	}

	return records, nil
}

// ParseOSMShard extracts spatial features (buildings, roads, land-use
// polygons) from an OpenStreetMap PBF shard.
//
// TODO(production): Use paulmach/osm to decode the PBF format.
func ParseOSMShard(raw []byte, shardID string) ([]Record, error) {
	if len(raw) < 4 {
		return nil, fmt.Errorf("osm shard payload too small (%d bytes)", len(raw))
	}

	h := sha256.Sum256(raw)
	seed := binary.LittleEndian.Uint64(h[:8])

	osmFeatures := []string{
		"building", "road_primary", "road_secondary",
		"park", "water_body", "industrial", "residential",
		"commercial", "agricultural",
	}

	const featuresPerShard = 80
	records := make([]Record, 0, featuresPerShard)

	for i := range featuresPerShard {
		feature := osmFeatures[i%len(osmFeatures)]
		lat := 34.0 + float64(i)*0.005
		lon := -118.0 + float64(i)*0.005
		density := math.Abs(math.Cos(float64(seed)+float64(i)*0.3)) * 100

		records = append(records, Record{
			TileID:    shardID,
			Lat:       lat,
			Lon:       lon,
			Band:      "osm_density",
			Value:     math.Round(density*100) / 100,
			Timestamp: 1709251200000,
			LULCClass: feature,
		})
	}

	return records, nil
}
