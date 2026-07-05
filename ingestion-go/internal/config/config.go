package config

import (
	"errors"
	"fmt"
	"strconv"
	"strings"
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

type LandsatConfig struct {
	STACURL   string
	BBox      BBox
	StartYear int
	EndYear   int
	MaxCloud  float64
	Bands     []string
}

func DefaultLandsatConfig() LandsatConfig {
	return LandsatConfig{
		STACURL:   "https://landsatlook.usgs.gov/stac-server",
		BBox:      BBox{80.0, 12.8, 80.4, 13.2},
		StartYear: 2014,
		EndYear:   2023,
		MaxCloud:  10,
		Bands:     []string{"B2", "B3", "B4", "B5", "B6", "B10"},
	}
}
