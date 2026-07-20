package parser

import (
	"bytes"
	"fmt"
	"image"
	"os"

	"golang.org/x/image/tiff"
)

// ComputeAOICloudCover computes the cloud cover fraction specifically within
// the provided bounding box (minLon, minLat, maxLon, maxLat).
// It returns (cloudFraction, error). cloudFraction is [0.0, 100.0].
// Returns -1.0 if the AOI does not intersect the scene.
func ComputeAOICloudCover(qaPath string, bbox [4]float64) (float64, error) {
	raw, err := os.ReadFile(qaPath)
	if err != nil {
		return 0, fmt.Errorf("read qa: %w", err)
	}
	img, err := tiff.Decode(bytes.NewReader(raw))
	if err != nil {
		return 0, fmt.Errorf("decode qa: %w", err)
	}

	gt := parseTIFFGeotransform(raw)
	bounds := img.Bounds()
	w := bounds.Dx()
	// h := bounds.Dy()

	var qaPixels []int32
	switch i := img.(type) {
	case *image.Gray:
		qaPixels = make([]int32, len(i.Pix))
		for k, v := range i.Pix {
			qaPixels[k] = int32(v)
		}
	case *image.Gray16:
		qaPixels = make([]int32, len(i.Pix)/2)
		for k := 0; k < len(i.Pix); k += 2 {
			qaPixels[k/2] = int32(uint16(i.Pix[k])<<8 | uint16(i.Pix[k+1]))
		}
	default:
		return 0, fmt.Errorf("unsupported qa image format")
	}

	minLon, minLat, maxLon, maxLat := bbox[0], bbox[1], bbox[2], bbox[3]

	var totalAOIPixels int64
	var clearAOIPixels int64

	for idx, qa := range qaPixels {
		// 0 = fill. We only count valid data pixels.
		if qa == 0 {
			continue
		}

		row := idx / w
		col := idx % w

		x := gt.xOrigin + (float64(col)+0.5)*gt.xPixelSize
		y := gt.yOrigin + (float64(row)+0.5)*gt.yPixelSize

		lat, lon := y, x
		if gt.utmZone > 0 {
			lat, lon = utmToLatLon(x, y, gt.utmZone)
		}

		// Check if pixel is inside the AOI bounding box
		if lon >= minLon && lon <= maxLon && lat >= minLat && lat <= maxLat {
			totalAOIPixels++
			// bit 1: dilated cloud, bit 2: cirrus, bit 3: cloud, bit 4: cloud shadow
			// The qaFilter function checks if (qa & 0b11111) == 0.
			if qaFilter(qa) {
				clearAOIPixels++
			}
		}
	}

	if totalAOIPixels == 0 {
		return -1.0, nil
	}

	cloudy := totalAOIPixels - clearAOIPixels
	cloudFraction := (float64(cloudy) / float64(totalAOIPixels)) * 100.0
	return cloudFraction, nil
}
