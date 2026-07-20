package main

import (
	"fmt"
	"log"

	"github.com/helios/ingestion/internal/parser"
)

func main() {
	records := []parser.Record{
		{TileID: "test-tile-1", Lat: 34.01, Lon: -118.01, Band: "B10_TIR", Value: 295.5, Timestamp: 1709251200000, LULCClass: "urban"},
		{TileID: "test-tile-1", Lat: 34.02, Lon: -118.02, Band: "B10_TIR", Value: 296.1, Timestamp: 1709251200000, LULCClass: "water"},
		{TileID: "test-tile-2", Lat: 34.03, Lon: -118.03, Band: "B4_Red", Value: 0.15, Timestamp: 1709251200000, LULCClass: "forest"},
	}

	outPath := "test_output.parquet"
	if err := parser.WriteRecords(outPath, records); err != nil {
		log.Fatalf("Write failed: %v", err)
	}
	fmt.Printf("Successfully wrote %d records to %s\n", len(records), outPath)
}
