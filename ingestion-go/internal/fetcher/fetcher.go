// Package fetcher handles HTTP-based retrieval of remote geospatial
// data (Landsat GeoTIFFs and OSM extracts).
//
// It enforces timeouts, retries with exponential backoff, and respects
// context cancellation so the worker pool can shut down cleanly.
package fetcher

import (
	"context"
	"fmt"
	"io"
	"math"
	"net/http"
	"time"
)

const (
	// maxRetries is the number of retry attempts per fetch.
	maxRetries = 3
	// initialBackoff is the base delay between retries.
	initialBackoff = 500 * time.Millisecond
	// perRequestTimeout caps a single HTTP round-trip.
	perRequestTimeout = 2 * time.Minute
	// maxResponseBytes limits download size to 512 MiB to prevent OOM.
	maxResponseBytes = 512 << 20
)

// client is a shared HTTP client with sensible defaults.
var client = &http.Client{
	Timeout: perRequestTimeout,
	// TODO(production): Configure TLS min version, proxy, etc.
}

// Fetch downloads the resource at url, returning the raw bytes.
// It retries transient failures with exponential backoff.
func Fetch(ctx context.Context, url string) ([]byte, error) {
	var lastErr error

	for attempt := range maxRetries {
		if ctx.Err() != nil {
			return nil, ctx.Err()
		}

		body, err := doRequest(ctx, url)
		if err == nil {
			return body, nil
		}
		lastErr = err

		// Exponential backoff: 500ms, 1s, 2s, …
		backoff := time.Duration(float64(initialBackoff) * math.Pow(2, float64(attempt)))
		select {
		case <-ctx.Done():
			return nil, ctx.Err()
		case <-time.After(backoff):
		}
	}

	return nil, fmt.Errorf("fetch %s failed after %d attempts: %w", url, maxRetries, lastErr)
}

func doRequest(ctx context.Context, url string) ([]byte, error) {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, url, nil)
	if err != nil {
		return nil, fmt.Errorf("build request: %w", err)
	}
	req.Header.Set("User-Agent", "helios-ingestion/1.0")

	resp, err := client.Do(req)
	if err != nil {
		return nil, fmt.Errorf("http get: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return nil, fmt.Errorf("http %d from %s", resp.StatusCode, url)
	}

	// Guard against absurdly large responses.
	limited := io.LimitReader(resp.Body, maxResponseBytes)
	body, err := io.ReadAll(limited)
	if err != nil {
		return nil, fmt.Errorf("read body: %w", err)
	}
	return body, nil
}
