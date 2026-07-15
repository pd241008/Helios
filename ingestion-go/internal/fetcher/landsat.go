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

// Scene groups all band assets and calibration constants for one Landsat acquisition
// across both the L2 SR/ST and TOA collections.
type Scene struct {
	SceneID    string
	DateTime   time.Time
	CloudCover float64
	WRSPath    int
	WRSRow     int
	Assets     map[string]string // band key → download URL
	K1Band10   float64
	K2Band10   float64
	K1Band11   float64
	K2Band11   float64
}

// sceneKey returns a composite key for matching scenes across STAC collections.
func sceneKey(f STACFeature) string {
	date := ""
	if t, err := time.Parse(time.RFC3339, f.Properties.Datetime); err == nil {
		date = t.Format("2006-01-02")
	}
	return fmt.Sprintf("%d/%d/%s", int(f.Properties.WRSPath), int(f.Properties.WRSRow), date)
}

func searchCollection(ctx context.Context, client *STACClient, collection string, cfg config.Config) ([]STACFeature, error) {
	datetime := fmt.Sprintf("%d-01-01T00:00:00Z/%d-12-31T23:59:59Z",
		cfg.StartYear, cfg.EndYear)
	bbox := []float64{cfg.BBox[0], cfg.BBox[1], cfg.BBox[2], cfg.BBox[3]}

	req := STACSearchRequest{
		Collections: []string{collection},
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

	return client.Search(ctx, req)
}

// DiscoverSplitWindowScenes searches both the L2 SR/ST and TOA collections for the
// same bbox/date/cloud-cover filters and merges matching acquisitions into Scene
// values containing all band URLs (B4, B5, B10, B11 from TOA; ST_B10, QA_PIXEL
// from L2) plus per-scene thermal calibration constants.
func DiscoverSplitWindowScenes(ctx context.Context, cfg config.Config) ([]Scene, error) {
	client := NewSTACClient(cfg.STACURL)

	l2Features, err := searchCollection(ctx, client, cfg.CollectionL2, cfg)
	if err != nil {
		return nil, fmt.Errorf("search L2: %w", err)
	}

	toaFeatures, err := searchCollection(ctx, client, cfg.CollectionTOA, cfg)
	if err != nil {
		return nil, fmt.Errorf("search TOA: %w", err)
	}

	l2ByKey := make(map[string]STACFeature, len(l2Features))
	for _, f := range l2Features {
		l2ByKey[sceneKey(f)] = f
	}

	var scenes []Scene
	for _, toa := range toaFeatures {
		key := sceneKey(toa)
		l2, ok := l2ByKey[key]
		if !ok {
			continue
		}

		acqTime, _ := time.Parse(time.RFC3339, toa.Properties.Datetime)

		s := Scene{
			SceneID:    toa.ID,
			DateTime:   acqTime,
			CloudCover: toa.Properties.CloudCover,
			WRSPath:    int(toa.Properties.WRSPath),
			WRSRow:     int(toa.Properties.WRSRow),
			Assets:     make(map[string]string, 6),
			K1Band10:   toa.Properties.K1ConstantBand10,
			K2Band10:   toa.Properties.K2ConstantBand10,
			K1Band11:   toa.Properties.K1ConstantBand11,
			K2Band11:   toa.Properties.K2ConstantBand11,
		}

		for _, bk := range []string{"B4", "B5", "B10", "B11"} {
			if a, ok := toa.Assets[bk]; ok {
				s.Assets[bk] = client.ResolveURL(a.HRef)
			}
		}
		for _, bk := range []string{"ST_B10", "QA_PIXEL"} {
			if a, ok := l2.Assets[bk]; ok {
				s.Assets[bk] = client.ResolveURL(a.HRef)
			}
		}

		scenes = append(scenes, s)
	}

	return scenes, nil
}

// QABitmaskFilter returns true when no bits 0-4 are set in the QA_PIXEL value.
// Bits: 0=fill, 1=dilated cloud, 2=cirrus, 3=cloud, 4=cloud shadow.
func QABitmaskFilter(qaValue uint16) bool {
	return qaValue&0b11111 == 0
}
