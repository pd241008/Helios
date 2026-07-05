package fetcher

import (
	"context"
	"fmt"
	"io"
	"math"
	"net/http"
	"os"
	"path/filepath"
	"time"
)

const (
	maxRetries        = 3
	initialBackoff    = 500 * time.Millisecond
	perRequestTimeout = 2 * time.Minute
	maxResponseBytes  = 512 << 20
)

var client = &http.Client{
	Timeout: perRequestTimeout,
}

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

		backoff := time.Duration(float64(initialBackoff) * math.Pow(2, float64(attempt)))
		select {
		case <-ctx.Done():
			return nil, ctx.Err()
		case <-time.After(backoff):
		}
	}

	return nil, fmt.Errorf("fetch %s failed after %d attempts: %w", url, maxRetries, lastErr)
}

func FetchToFile(ctx context.Context, url, destPath string) (int64, error) {
	if err := os.MkdirAll(filepath.Dir(destPath), 0o750); err != nil {
		return 0, fmt.Errorf("mkdir %s: %w", filepath.Dir(destPath), err)
	}

	f, err := os.Create(destPath)
	if err != nil {
		return 0, fmt.Errorf("create %s: %w", destPath, err)
	}
	defer f.Close()

	var totalWritten int64

	for attempt := range maxRetries {
		if ctx.Err() != nil {
			return totalWritten, ctx.Err()
		}

		written, err := doStreamRequest(ctx, url, f)
		if err == nil {
			return written, nil
		}
		totalWritten = written

		backoff := time.Duration(float64(initialBackoff) * math.Pow(2, float64(attempt)))
		select {
		case <-ctx.Done():
			return totalWritten, ctx.Err()
		case <-time.After(backoff):
		}
	}

	return totalWritten, fmt.Errorf("fetch %s to file failed after %d attempts", url, maxRetries)
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

	limited := io.LimitReader(resp.Body, maxResponseBytes)
	body, err := io.ReadAll(limited)
	if err != nil {
		return nil, fmt.Errorf("read body: %w", err)
	}
	return body, nil
}

func doStreamRequest(ctx context.Context, url string, w io.Writer) (int64, error) {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, url, nil)
	if err != nil {
		return 0, fmt.Errorf("build request: %w", err)
	}
	req.Header.Set("User-Agent", "helios-ingestion/1.0")

	resp, err := client.Do(req)
	if err != nil {
		return 0, fmt.Errorf("http get: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return 0, fmt.Errorf("http %d from %s", resp.StatusCode, url)
	}

	written, err := io.Copy(w, io.LimitReader(resp.Body, maxResponseBytes))
	if err != nil {
		return written, fmt.Errorf("stream body: %w", err)
	}
	return written, nil
}
