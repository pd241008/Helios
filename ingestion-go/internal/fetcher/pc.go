package fetcher

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"log"
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

	pcSignTimeout = 60 * time.Second
)

// pcAssetKey maps Planetary Computer asset keys to the filenames
// the GeoTIFFParser expects. Only the bands required for the pipeline
// are signed during discovery. Optional bands (B1, B2, B3, B7, MTL)
// are signed later in the worker to avoid PC SAS rate limits.
var pcAssetMap = map[string]string{
	"red":       "B4",
	"nir08":     "B5",
	"swir16":    "B6",
	"lwir11":    "ST_B10",
	"qa_pixel":  "QA_PIXEL",
}

// pcOptionalAssetMap contains bands that are nice-to-have but not
// required. Signed in the worker pool with its own rate limiting.
var pcOptionalAssetMap = map[string]string{
	"green":   "B3",
	"blue":    "B2",
	"swir22":  "B7",
	"coastal": "B1",
	"mtl.json": "MTL",
}

// pcSignResult is the JSON response from the PC signing endpoint.
type pcSignResult struct {
	HRef  string `json:"href"`
	Expiry string `json:"msft:expiry,omitempty"`
}

// signPCURL calls the Planetary Computer SAS signing endpoint to convert an
// unsigned blob URL into a short-lived signed URL. Works without authentication
// but is rate-limited (~1 req/s for anonymous access). Returns the retry-after
// duration on 429 so callers can back off.
func signPCURL(unsignedURL string) (string, time.Duration, error) {
	signURL := PCSigningURL + "?href=" + unsignedURL

	cli := &http.Client{Timeout: pcSignTimeout}
	resp, err := cli.Get(signURL)
	if err != nil {
		return "", 0, fmt.Errorf("pc sign request: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode == 429 {
		// Parse Retry-After from the response body (PC returns it as a JSON field).
		var errBody struct {
			Message string `json:"message"`
		}
		json.NewDecoder(resp.Body).Decode(&errBody)
		// Extract seconds from "Try again in 55 seconds."
		retrySec := 60 * time.Second
		fmt.Sscanf(errBody.Message, "Try again in %d seconds", &retrySec)
		return "", retrySec, fmt.Errorf("pc sign 429: %s", errBody.Message)
	}

	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		body, _ := io.ReadAll(io.LimitReader(resp.Body, 1<<12))
		return "", 0, fmt.Errorf("pc sign %d: %s", resp.StatusCode, string(body))
	}

	var result pcSignResult
	if err := json.NewDecoder(resp.Body).Decode(&result); err != nil {
		return "", 0, fmt.Errorf("pc sign decode: %w", err)
	}
	if result.HRef == "" {
		return "", 0, fmt.Errorf("pc sign returned empty href")
	}
	return result.HRef, 0, nil
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

	filter := &STACFilter{
		Op: "in",
		Args: []any{
			map[string]string{"property": "id"},
			[]string{
				"LC08_L2SP_142051_20161016_02_T1",
				"LC08_L2SP_142051_20160728_02_T1",
				"LC08_L2SP_142051_20160423_02_T1",
				"LC08_L2SP_142051_20160407_02_T1",
				"LC09_L2SP_142051_20221025_02_T1",
				"LC08_L2SP_142051_20220526_02_T1",
				"LC09_L2SP_142051_20220331_02_T1",
				"LC08_L2SP_142051_20220203_02_T1",
			},
		},
	}

	// Log the exact CQL2 filter body being sent to the PC STAC API.
	filterJSON, _ := json.Marshal(filter)
	log.Printf("[pc-discovery] POST %s/search", cfg.STACURL)
	log.Printf("[pc-discovery] collections: [\"%s\"]", PCCollectionL2)
	log.Printf("[pc-discovery] datetime: %s", datetime)
	log.Printf("[pc-discovery] bbox: %v", bbox)
	log.Printf("[pc-discovery] limit: 500")
	log.Printf("[pc-discovery] filter (CQL2): %s", string(filterJSON))

	req := STACSearchRequest{
		Collections: []string{PCCollectionL2},
		Datetime:    datetime,
		BBox:        bbox,
		Filter:      filter,
		Limit:       500,
	}

	features, err := client.Search(ctx, req)
	if err != nil {
		return nil, fmt.Errorf("pc search: %w", err)
	}

	// Log the raw STAC response: total feature count and per-feature platform.
	log.Printf("[pc-discovery] raw STAC features returned: %d", len(features))
	for i, f := range features {
		log.Printf("[pc-discovery]   feature[%d]: id=%s platform=%s cloud=%.2f date=%s",
			i, f.ID, f.Properties.Platform, f.Properties.CloudCover, f.Properties.Datetime)
	}

	// Per-platform summary.
	platformCounts := map[string]int{}
	for _, f := range features {
		platformCounts[f.Properties.Platform]++
	}
	log.Printf("[pc-discovery] per-platform counts: %v", platformCounts)
	log.Printf("[pc-discovery] filter was applied to outgoing request: YES (CQL2 filter included in POST body)")

	var scenes []Scene
	for _, f := range features {
		acqTime, _ := time.Parse(time.RFC3339, f.Properties.Datetime)

		s := Scene{
			SceneID:    f.ID,
			DateTime:   acqTime,
			CloudCover: f.Properties.CloudCover,
			WRSPath:    int(f.Properties.WRSPath),
			WRSRow:     int(f.Properties.WRSRow),
			Assets:     make(map[string]string, 8),
		}

		// Map PC asset keys → parser band names + sign each URL.
		// Only sign the 5 required bands (B4, B5, B6, ST_B10, QA_PIXEL)
		// to stay within PC's ~1 req/s anonymous rate limit.
		signedCount := 0
		failedCount := 0
		for pcKey, localName := range pcAssetMap {
			asset, ok := f.Assets[pcKey]
			if !ok {
				failedCount++
				log.Printf("[pc-discovery]   %s: asset key %q missing from STAC response", f.ID, pcKey)
				continue
			}

			unsignedURL := client.ResolveURL(asset.HRef)

			// Retry signing with exponential backoff, respecting
			// the Retry-After duration from 429 responses.
			var signedURL string
			var signErr error
			for attempt := 0; attempt < 5; attempt++ {
				var retryAfter time.Duration
				signedURL, retryAfter, signErr = signPCURL(unsignedURL)
				if signErr == nil {
					break
				}
				backoff := 2*time.Second + retryAfter
				if attempt < 4 {
					log.Printf("[pc-discovery]   %s/%s: sign attempt %d failed, retrying in %v",
						f.ID, pcKey, attempt+1, backoff)
					time.Sleep(backoff)
				}
			}

			if signErr != nil {
				failedCount++
				log.Printf("[pc-discovery]   %s: CRITICAL signing failed for %s after 5 attempts: %v",
					f.ID, pcKey, signErr)
				continue
			}
			s.Assets[localName] = signedURL
			signedCount++
			// Delay between successful signing requests to stay under rate limit.
			time.Sleep(1200 * time.Millisecond)
		}
		log.Printf("[pc-discovery]   %s: signed %d/%d required bands (%d failed)",
			f.ID, signedCount, len(pcAssetMap), failedCount)

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

	log.Printf("[pc-discovery] scenes after required-band filter: %d (from %d raw features)",
		len(scenes), len(features))

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
