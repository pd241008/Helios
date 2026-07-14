package config

import (
	"errors"
	"fmt"
	"strconv"
	"strings"
	"time"
)

type BBox [4]float64

func ParseBBox(s string) (BBox, error) {
	parts := strings.Split(s, ",")
	if len(parts) != 4 {
		return BBox{}, errors.New("bbox must be min_lon,min_lat,max_lon,max_lat")
	}
	var b BBox
	for i, p := range parts {
		v, err := strconv.ParseFloat(strings.TrimSpace(p), 64)
		if err != nil {
			return BBox{}, fmt.Errorf("invalid bbox coord %q: %w", p, err)
		}
		b[i] = v
	}
	return b, nil
}

type Config struct {
	STACURL          string
	BBox             BBox
	StartYear        int
	EndYear          int
	MaxCloud         float64
	Bands            []string
	CollectionL2     string
	CollectionTOA    string
	FetchSplitWindow bool
	Workers          int
	RetryAttempts    int
	RetryBackoff     time.Duration
	StagingDir       string
	OSMExtractPath   string
}

func DefaultConfig() Config {
	return Config{
		STACURL:          "https://planetarycomputer.microsoft.com/api/stac/v1",
		BBox:             BBox{79.9469, 12.8, 80.345, 13.23},
		StartYear:        2014,
		EndYear:          2023,
		MaxCloud:         10,
		Bands:            []string{"B2", "B3", "B4", "B5", "B6", "B10"},
		CollectionL2:     "landsat-c2-l2",
		CollectionTOA:    "landsat-8-c2-l1",
		FetchSplitWindow: false,
		Workers:          8,
		RetryAttempts:    3,
		RetryBackoff:     500 * time.Millisecond,
		StagingDir:       "./staging",
		OSMExtractPath:   "",
	}
}

func DefaultLandsatConfig() Config {
	return DefaultConfig()
}

type LandsatConfig = Config
