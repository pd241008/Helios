package fetcher

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strings"
	"time"
)

const stacRequestTimeout = 30 * time.Second

type STACFilter struct {
	Op   string `json:"op"`
	Args []any  `json:"args"`
}

type STACSearchRequest struct {
	Collections []string   `json:"collections"`
	Datetime    string     `json:"datetime"`
	BBox        []float64  `json:"bbox"`
	Filter      *STACFilter `json:"filter,omitempty"`
	Limit       int        `json:"limit"`
}

type STACResponse struct {
	Type     string        `json:"type"`
	Features []STACFeature `json:"features"`
	Links    []STACLink    `json:"links"`
}

type STACFeature struct {
	ID         string              `json:"id"`
	Properties STACProperties      `json:"properties"`
	Assets     map[string]STACAsset `json:"assets"`
	Geometry   json.RawMessage     `json:"geometry"`
}

type STACProperties struct {
	Datetime          string     `json:"datetime"`
	CloudCover        float64    `json:"eo:cloud_cover"`
	WRSPath           FlexInt    `json:"landsat:wrs_path,omitempty"`
	WRSRow            FlexInt    `json:"landsat:wrs_row,omitempty"`
	K1ConstantBand10  float64    `json:"landsat:const1_band_10,omitempty"`
	K2ConstantBand10  float64    `json:"landsat:const2_band_10,omitempty"`
	K1ConstantBand11  float64    `json:"landsat:const1_band_11,omitempty"`
	K2ConstantBand11  float64    `json:"landsat:const2_band_11,omitempty"`
}

// FlexInt accepts JSON number or string token in quotes. PC returns
// landsat:wrs_path as a string, LandsatLook returns a number.
type FlexInt int

func (f *FlexInt) UnmarshalJSON(b []byte) error {
	if len(b) == 0 || string(b) == "null" {
		return nil
	}
	// Try number first
	if err := json.Unmarshal(b, (*int)(f)); err == nil {
		return nil
	}
	// Fall back to string
	var s string
	if err := json.Unmarshal(b, &s); err != nil {
		return err
	}
	var v int
	if _, err := fmt.Sscanf(s, "%d", &v); err != nil {
		return err
	}
	*f = FlexInt(v)
	return nil
}

type STACAsset struct {
	HRef  string `json:"href"`
	Type  string `json:"type"`
	Title string `json:"title"`
}

type STACLink struct {
	Rel  string `json:"rel"`
	HRef string `json:"href"`
	Type string `json:"type"`
}

type STACClient struct {
	baseURL string
	client  *http.Client
}

func NewSTACClient(baseURL string) *STACClient {
	return &STACClient{
		baseURL: strings.TrimRight(baseURL, "/"),
		client:  &http.Client{Timeout: stacRequestTimeout},
	}
}

func (s *STACClient) Search(ctx context.Context, req STACSearchRequest) ([]STACFeature, error) {
	var features []STACFeature
	searchURL := s.baseURL + "/search"

	for {
		resp, err := s.doSearch(ctx, searchURL, req)
		if err != nil {
			return nil, fmt.Errorf("stac search: %w", err)
		}
		features = append(features, resp.Features...)

		nextURL := ""
		for _, link := range resp.Links {
			if link.Rel == "next" {
				nextURL = link.HRef
				break
			}
		}
		if nextURL == "" {
			break
		}
		searchURL = nextURL
		req = STACSearchRequest{}
	}

	return features, nil
}

func (s *STACClient) doSearch(ctx context.Context, searchURL string, req STACSearchRequest) (*STACResponse, error) {
	var bodyReader io.Reader
	if req.Collections != nil {
		body, err := json.Marshal(req)
		if err != nil {
			return nil, fmt.Errorf("marshal request: %w", err)
		}
		bodyReader = bytes.NewReader(body)
	}

	httpReq, err := http.NewRequestWithContext(ctx, http.MethodPost, searchURL, bodyReader)
	if err != nil {
		return nil, fmt.Errorf("build request: %w", err)
	}
	httpReq.Header.Set("Content-Type", "application/json")
	httpReq.Header.Set("User-Agent", "helios-ingestion/1.0")

	httpResp, err := s.client.Do(httpReq)
	if err != nil {
		return nil, fmt.Errorf("http post: %w", err)
	}
	defer httpResp.Body.Close()

	if httpResp.StatusCode < 200 || httpResp.StatusCode >= 300 {
		respBody, _ := io.ReadAll(io.LimitReader(httpResp.Body, 1<<16))
		return nil, fmt.Errorf("stac api %d: %s", httpResp.StatusCode, string(respBody))
	}

	var stacResp STACResponse
	if err := json.NewDecoder(httpResp.Body).Decode(&stacResp); err != nil {
		return nil, fmt.Errorf("decode response: %w", err)
	}

	return &stacResp, nil
}

func (s *STACClient) ResolveURL(relativeURL string) string {
	if strings.HasPrefix(relativeURL, "http") {
		return relativeURL
	}
	return s.baseURL + "/" + strings.TrimLeft(relativeURL, "/")
}
