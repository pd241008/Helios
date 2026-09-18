package main

import (
"context"
"fmt"
"io"
"log"
"net/http"

"github.com/helios/ingestion/internal/config"
"github.com/helios/ingestion/internal/fetcher"
"github.com/helios/ingestion/internal/parser"
)

func main() {
cfg := config.Config{
STACURL:          "https://planetarycomputer.microsoft.com/api/stac/v1",
BBox:             [4]float64{77.34, 12.83, 77.90, 13.16},
StartYear:        2016,
EndYear:          2026,
MaxCloud:         30,
MaxAOICloud:      10,
CollectionL2:     "landsat-c2-l2",
FetchSplitWindow: true,
Limit:            500,
}

scenes, err := fetcher.DiscoverPCSplitWindowScenes(context.Background(), cfg)
if err != nil {
log.Fatalf("Error: %v", err)
}

fmt.Printf("Total candidates: %d\n", len(scenes))
retained := 0

for _, s := range scenes {
qaURL, ok := s.Assets["QA_PIXEL"]
if !ok {
continue
}

// Sign URL
signedQA, _, err := fetcher.SignPCURL(qaURL)
if err != nil {
continue
}

// Download QA
req, _ := http.NewRequestWithContext(context.Background(), "GET", signedQA, nil)
resp, err := http.DefaultClient.Do(req)
if err != nil {
continue
}
qaData, err := io.ReadAll(resp.Body)
resp.Body.Close()
if err != nil {
continue
}

// Parse AOI cloud cover
aoiCloud, err := parser.ComputeAOICloudCoverBytes(qaData, cfg.BBox)
if err != nil {
continue
}

fmt.Printf("Scene %s: AOI cloud = %.2f%%\n", s.SceneID, aoiCloud)

if aoiCloud <= float64(cfg.MaxAOICloud) {
retained++
}
}
fmt.Printf("Total retained: %d\n", retained)
}
