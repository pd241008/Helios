package main

import (
	"fmt"
	"os"
	"time"

	"github.com/helios/ingestion/internal/parser"
)

func readMemMB() int64 {
	data, err := os.ReadFile("/proc/self/status")
	if err != nil {
		return 0
	}
	for _, line := range splitLines(data) {
		if hasPrefix(line, []byte("VmRSS:")) {
			var kb int64
			fmt.Sscanf(string(line), "VmRSS: %d kB", &kb)
			return kb / 1024
		}
	}
	return 0
}

func splitLines(data []byte) [][]byte {
	var lines [][]byte
	start := 0
	for i, b := range data {
		if b == '\n' {
			lines = append(lines, data[start:i])
			start = i + 1
		}
	}
	return lines
}

func hasPrefix(data, prefix []byte) bool {
	if len(data) < len(prefix) {
		return false
	}
	for i := range prefix {
		if data[i] != prefix[i] {
			return false
		}
	}
	return true
}

func main() {
	sceneDir := "/root/workspace/workspace/03-Code/Projects/Legacy/Helios/staging/raw/landsat/LC08_L2SP_142051_20231020_02_T1"
	sceneID := "LC08_L2SP_142051_20231020_02_T1"
	ts := time.Date(2023, 10, 20, 4, 58, 38, 0, time.UTC)
	outPath := "/tmp/stream-test-output.parquet"

	fmt.Println("=== Streaming Parquet Writer Verification ===")
	fmt.Printf("Scene dir: %s\n", sceneDir)
	fmt.Println()

	memBefore := readMemMB()
	fmt.Printf("Memory before parse: %d MB (RSS)\n", memBefore)

	parsed := parser.NewGeoTIFFParser(sceneID, sceneDir, ts)

	start := time.Now()
	sw, err := parser.NewParquetStreamWriter(outPath)
	if err != nil {
		fmt.Fprintf(os.Stderr, "Create writer: %v\n", err)
		os.Exit(1)
	}

	count, err := parsed.WriteStreaming(sw)
	if err != nil {
		fmt.Fprintf(os.Stderr, "WriteStreaming: %v\n", err)
		os.Exit(1)
	}

	if err := sw.Close(); err != nil {
		fmt.Fprintf(os.Stderr, "Close writer: %v\n", err)
		os.Exit(1)
	}

	elapsed := time.Since(start)
	memAfter := readMemMB()

	fmt.Printf("Records written:    %d\n", count)
	fmt.Printf("Elapsed:            %s\n", elapsed)
	fmt.Printf("Memory after parse: %d MB (RSS)\n", memAfter)
	fmt.Printf("Peak memory delta:  %d MB\n", memAfter-memBefore)

	finfo, _ := os.Stat(outPath)
	if finfo != nil {
		fmt.Printf("Parquet file size:  %.1f MB\n", float64(finfo.Size())/1e6)
	}
	fmt.Println()

	// Expected: ~252M records for a full Landsat scene with 7 bands
	// Peak memory should be ~400-600 MB (1 TIFF + 1 float64 array), NOT ~25 GB
	fmt.Println("=== PASS: Streaming writer completed without OOM ===")
}
