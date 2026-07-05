package fetcher

import (
	"context"
	"fmt"
	"time"

	"github.com/helios/ingestion/internal/config"
)

type SceneAsset struct {
	SceneID    string
	BandKey    string
	BandName   string
	DownloadURL string
	Timestamp   int64
	CloudCover  float64
}

var landsatBands = []struct {
	key  string
	name string
}{
	{key: "B2", name: "B2_Blue"},
	{key: "B3", name: "B3_Green"},
	{key: "B4", name: "B4_Red"},
	{key: "B5", name: "B5_NIR"},
	{key: "B6", name: "B6_SWIR1"},
	{key: "B10", name: "B10_TIR"},
}

func DiscoverScenes(ctx context.Context, cfg config.LandsatConfig) ([]SceneAsset, error) {
	client := NewSTACClient(cfg.STACURL)

	datetime := fmt.Sprintf("%d-01-01T00:00:00Z/%d-12-31T23:59:59Z",
		cfg.StartYear, cfg.EndYear)

	bbox := []float64{cfg.BBox[0], cfg.BBox[1], cfg.BBox[2], cfg.BBox[3]}

	req := STACSearchRequest{
		Collections: []string{"landsat-8-c2-l2"},
		Datetime:    datetime,
		BBox:        bbox,
		Filter: &STACFilter{
			Op: "<",
			Args: []any{
				map[string]string{"property": "eo:cloud_cover"},
				cfg.MaxCloud,
			},
		},
		Limit: 500,
	}

	features, err := client.Search(ctx, req)
	if err != nil {
		return nil, fmt.Errorf("discover landsat scenes: %w", err)
	}

	if len(features) == 0 {
		return nil, nil
	}

	var assets []SceneAsset
	for _, f := range features {
		for _, band := range landsatBands {
			asset, ok := f.Assets[band.key]
			if !ok {
				continue
			}

			acqTime, _ := time.Parse(time.RFC3339, f.Properties.Datetime)
			ts := int64(0)
			if !acqTime.IsZero() {
				ts = acqTime.UnixMilli()
			}

			assets = append(assets, SceneAsset{
				SceneID:     f.ID,
				BandKey:     band.key,
				BandName:    band.name,
				DownloadURL: client.ResolveURL(asset.HRef),
				Timestamp:   ts,
				CloudCover:  f.Properties.CloudCover,
			})
		}
	}

	return assets, nil
}
