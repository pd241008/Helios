package fetcher

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strings"
	"time"

	"github.com/helios/ingestion/internal/config"
)

// PC_* constants for Microsoft Planetary Computer.
const (
	PCSTACBaseURL  = "https://planetarycomputer.microsoft.com/api/stac/v1"
	PCSigningURL   = "https://planetarycomputer.microsoft.com/api/sas/v1/sign"
	PCCollectionL2 = "landsat-c2-l2"

	pcSignTimeout = 30 * time.Second
)

// pcAssetKey maps Planetary Computer asset keys to the filenames
// the GeoTIFFParser expects.
var pcAssetMap = map[string]string{
	"red":       "B4",
	"nir08":     "B5",
	"swir16":    "B6",
	"lwir11":    "ST_B10",
	"qa_pixel":  "QA_PIXEL",
	"green":     "B3",
	"blue":      "B2",
	"swir22":    "B7",
	"coastal":   "B1",
	"mtl.json":  "MTL",
}

// pcSignResult is the JSON response from the PC signing endpoint.
type pcSignResult struct {
	HRef  string `json:"href"`
	Expiry string `json:"msft:expiry,omitempty"`
}

// signPCURL calls the Planetary Computer SAS signing endpoint to convert an
// unsigned blob URL into a short-lived signed URL. Works without authentication
// but is rate-limited.
func signPCURL(unsignedURL string) (string, error) {
	signURL := PCSigningURL + "?href=" + unsignedURL

	cli := &http.Client{Timeout: pcSignTimeout}
	resp, err := cli.Get(signURL)
	if err != nil {
		return "", fmt.Errorf("pc sign request: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		body, _ := io.ReadAll(io.LimitReader(resp.Body, 1<<12))
		return "", fmt.Errorf("pc sign %d: %s", resp.StatusCode, string(body))
	}

	var result pcSignResult
	if err := json.NewDecoder(resp.Body).Decode(&result); err != nil {
		return "", fmt.Errorf("pc sign decode: %w", err)
	}
	if result.HRef == "" {
		return "", fmt.Errorf("pc sign returned empty href")
	}
	return result.HRef, nil
}

// pcMTLMetadata holds relevant K1/K2 constants parsed from MTL.json.
type pcMTLMetadata struct {
	K1Band10 float64 `json:"k1_constant_band_10,omitempty"`
	K2Band10 float64 `json:"k2_constant_band_10,omitempty"`
	K1Band11 float64 `json:"k1_constant_band_11,omitempty"`
	K2Band11 float64 `json:"k2_constant_band_11,omitempty"`
}

// parsePCMTL parses K1/K2 constants from a USGS-style MTL.json.
// Returns zeroed metadata if parsing fails (caller may use defaults).
func parsePCMTL(data []byte) pcMTLMetadata {
	var doc struct {
		LandsatMetadata struct {
			ThermalConstants struct {
				K1Band10 *float64 `json:"K1_CONSTANT_BAND_10"`
				K2Band10 *float64 `json:"K2_CONSTANT_BAND_10"`
				K1Band11 *float64 `json:"K1_CONSTANT_BAND_11"`
				K2Band11 *float64 `json:"K2_CONSTANT_BAND_11"`
			} `json:"THERMAL_CONSTANTS"`
		} `json:"LANDSAT_METADATA_FILE"`
	}
	if err := json.Unmarshal(data, &doc); err != nil {
		return pcMTLMetadata{}
	}
	m := doc.LandsatMetadata.ThermalConstants
	if m.K1Band10 != nil {
		return pcMTLMetadata{K1Band10: *m.K1Band10, K2Band10: *m.K2Band10,
			K1Band11: *m.K1Band11, K2Band11: *m.K2Band11}
	}
	return pcMTLMetadata{}
}

// defaultK1K2 returns fallback constants for Landsat 8/9 Band 10

// when MTL.json is unavailable.
func defaultK1K2() (k1, k2 float64) { return 774.8853, 1321.0789 }

// DiscoverPCSplitWindowScenes searches the Planetary Computer STAC for Landsat
// Collection 2 Level-2 scenes matching the configured bbox/years/cloud cover,
// signs each asset URL via PC's SAS signing endpoint, and downloads MTL.json
// for K1/K2 constants. Returns Scene values ready for the split-window worker.
// Only the L2 collection is queried (PC already contains ST_B10).
func DiscoverPCSplitWindowScenes(ctx context.Context, cfg config.Config) ([]Scene, error) {
	client := NewSTACClient(cfg.STACURL)

	datetime := fmt.Sprintf("%d-01-01T00:00:00Z/%d-12-31T23:59:59Z",
		cfg.StartYear, cfg.EndYear)
	bbox := []float64{cfg.BBox[0], cfg.BBox[1], cfg.BBox[2], cfg.BBox[3]}

	req := STACSearchRequest{
		Collections: []string{PCCollectionL2},
		Datetime:    datetime,
		BBox:        bbox,
		Filter: &STACFilter{
			Op: "and",
			Args: []any{
				map[string]any{"op": "<", "args": []any{
					map[string]string{"property": "eo:cloud_cover"},
					cfg.MaxCloud,
				}},
				map[string]any{"op": "in", "args": []any{
					map[string]string{"property": "platform"},
					[]string{"landsat-8", "landsat-9"},
				}},
			},
		},
		Limit: 500,
	}

	features, err := client.Search(ctx, req)
	if err != nil {
		return nil, fmt.Errorf("pc search: %w", err)
	}

	var scenes []Scene
	for _, f := range features {
		acqTime, _ := time.Parse(time.RFC3339, f.Properties.Datetime)

		s := Scene{
			SceneID:    f.ID,
			DateTime:   acqTime,
			CloudCover: f.Properties.CloudCover,
			WRSPath:    f.Properties.WRSPath,
			WRSRow:     f.Properties.WRSRow,
			Assets:     make(map[string]string, 8),
		}

		// Map PC asset keys → parser band names + sign each URL
		for pcKey, localName := range pcAssetMap {
			asset, ok := f.Assets[pcKey]
			if !ok {
				continue
			}

			unsignedURL := client.ResolveURL(asset.HRef)
			signedURL, err := signPCURL(unsignedURL)
			if err != nil {
				// If signing fails for MTL, we can proceed with defaults.
				// If it fails for data bands, we skip the scene.
				if pcKey == "mtl.json" {
					continue
				}
				_ = err // log at caller
				continue
			}
			s.Assets[localName] = signedURL
		}

		// Need at least red, nir08, swir16, and QA_PIXEL to be useful
		required := []string{"B4", "B5", "B6", "QA_PIXEL", "ST_B10"}
		missing := false
		for _, r := range required {
			if _, ok := s.Assets[r]; !ok {
				missing = true
				break
			}
		}
		if missing {
			continue
		}

		// Try to extract K1/K2 from MTL.json (if signed successfully)
		if mtlURL, ok := s.Assets["MTL"]; ok {
			mtlData, err := fetchSignedJSON(ctx, mtlURL)
			if err == nil {
				mtlInfo := parsePCMTL(mtlData)
				if mtlInfo.K1Band10 != 0 {
					s.K1Band10 = mtlInfo.K1Band10
					s.K2Band10 = mtlInfo.K2Band10
					s.K1Band11 = mtlInfo.K1Band11
					s.K2Band11 = mtlInfo.K2Band11
				}
			}
		}
		if s.K1Band10 == 0 {
			s.K1Band10, s.K2Band10 = defaultK1K2()
			s.K1Band11, s.K2Band11 = 480.8883, 1201.1442
		}
		delete(s.Assets, "MTL")

		scenes = append(scenes, s)
	}

	return scenes, nil
}

// fetchSignedJSON downloads a signed URL and returns the JSON body.
func fetchSignedJSON(ctx context.Context, url string) ([]byte, error) {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, url, nil)
	if err != nil {
		return nil, err
	}
	req.Header.Set("User-Agent", "helios-ingestion/1.0")

	cli := &http.Client{Timeout: 30 * time.Second}
	resp, err := cli.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return nil, fmt.Errorf("http %d", resp.StatusCode)
	}
	body, err := io.ReadAll(io.LimitReader(resp.Body, 1<<20))
	if err != nil {
		return nil, err
	}
	return body, nil
}

// PCFallbackScene returns a minimal Scene for error recovery.
func PCFallbackScene() Scene {
	return Scene{
		SceneID:  "LC08_L2SP_142051_20230222_02_T1",
		DateTime: time.Date(2023, 2, 22, 0, 0, 0, 0, time.UTC),
	}
}

// IsPCURL reports whether url looks like a Planetary Computer Azure blob URL.
func IsPCURL(url string) bool {
	return strings.Contains(url, "planetarycomputer.microsoft.com") ||
		strings.Contains(url, "landsateuwest.blob.core.windows.net")
}
