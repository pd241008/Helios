package main

import (
"context"
"fmt"
"log"

"github.com/helios/ingestion/internal/config"
"github.com/helios/ingestion/internal/fetcher"
)

func main() {
cfg := config.DefaultConfig()
cfg.BBox = [4]float64{79.9469, 12.8, 80.345, 13.23}
cfg.StartYear = 2016
cfg.EndYear = 2026
cfg.MaxCloud = 10
cfg.Limit = 500
cfg.STACURL = "https://planetarycomputer.microsoft.com/api/stac/v1"

fmt.Println("Discovering scenes...")
scenes, err := fetcher.DiscoverPCSplitWindowScenes(context.Background(), cfg)
if err != nil {
log.Fatal(err)
}

fmt.Printf("Found %d scenes\n", len(scenes))
for _, s := range scenes {
if qaURL, ok := s.Assets["QA_PIXEL"]; ok {
fmt.Printf("QA_PIXEL for %s: %s\n", s.SceneID, qaURL)
}
}
}
