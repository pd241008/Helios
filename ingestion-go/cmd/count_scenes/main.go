package main

import (
"context"
"fmt"

"github.com/helios/ingestion/internal/config"
"github.com/helios/ingestion/internal/fetcher"
)

func main() {
cfg := config.Config{
STACURL:          "https://planetarycomputer.microsoft.com/api/stac/v1",
BBox:             [4]float64{77.34, 12.83, 77.90, 13.16},
StartYear:        2016,
EndYear:          2026,
MaxCloud:         30,
MaxAOICloud:      30, // just discovering, doesn't matter
CollectionL2:     "landsat-c2-l2",
FetchSplitWindow: true,
		Limit: 500,
}

scenes, err := fetcher.DiscoverPCSplitWindowScenes(context.Background(), cfg)
if err != nil {
fmt.Printf("Error: %v\n", err)
return
}
fmt.Printf("Candidates (<30%% cloud): %d\n", len(scenes))
}
