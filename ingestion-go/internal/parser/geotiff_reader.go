package parser

import (
	"bytes"
	"encoding/binary"
	"fmt"
	"image"
	"math"
	"os"
	"path/filepath"
	"strings"
	"time"

	"golang.org/x/image/tiff"
)

type GeoTIFFParser struct {
	SceneID   string
	SceneDir  string
	Timestamp time.Time
	LULCClass string

	bandNames     []string
	qaPixels     []int32
	width, height int
}

func NewGeoTIFFParser(sceneID, sceneDir string, ts time.Time) *GeoTIFFParser {
	return &GeoTIFFParser{
		SceneID:   sceneID,
		SceneDir:  sceneDir,
		Timestamp: ts,
		bandNames: []string{"B4", "B5", "B6", "B10", "B11", "ST_B10", "QA_PIXEL"},
	}
}

// Records returns all records for the scene in memory.
// Deprecated: use WriteStreaming for scenes that exceed available heap.
func (p *GeoTIFFParser) Records() ([]Record, error) {
	if err := p.loadQA(); err != nil {
		return nil, err
	}
	var records []Record
	for _, band := range p.bandNames {
		if band == "QA_PIXEL" {
			continue
		}
		rs, err := p.readBand(band)
		if err != nil {
			continue
		}
		records = append(records, rs...)
	}
	return records, nil
}

// WriteStreaming parses each band and writes records directly to the parquet
// writer one record at a time, without accumulating them in memory. Returns
// the total number of records written. Peak memory is ~1 TIFF image + 1
// float64 pixel array (typically 300-400 MB), not the full Record slice
// (which would be ~25 GB for a 252M-record scene).
func (p *GeoTIFFParser) WriteStreaming(sw *ParquetStreamWriter) (int64, error) {
	if err := p.loadQA(); err != nil {
		return 0, err
	}
	var total int64
	for _, band := range p.bandNames {
		if band == "QA_PIXEL" {
			continue
		}
		n, err := p.readBandStreaming(band, sw)
		if err != nil {
			continue
		}
		total += n
	}
	return total, nil
}

// --------------------------------------------------------------------------
// QA_PIXEL
// --------------------------------------------------------------------------

func (p *GeoTIFFParser) loadQA() error {
	qaPath := filepath.Join(p.SceneDir, "QA_PIXEL.tif")
	if _, err := os.Stat(qaPath); err != nil {
		return nil
	}
	raw, err := os.ReadFile(qaPath)
	if err != nil {
		return nil
	}
	img, err := tiff.Decode(bytes.NewReader(raw))
	if err != nil {
		return nil
	}
	switch i := img.(type) {
	case *image.Gray:
		p.width = i.Bounds().Dx()
		p.height = i.Bounds().Dy()
		p.qaPixels = make([]int32, p.width*p.height)
		for y := 0; y < p.height; y++ {
			off := y * i.Stride
			for x := 0; x < p.width; x++ {
				p.qaPixels[y*p.width+x] = int32(i.Pix[off+x])
			}
		}
	case *image.Gray16:
		p.width = i.Bounds().Dx()
		p.height = i.Bounds().Dy()
		p.qaPixels = make([]int32, p.width*p.height)
		for y := 0; y < p.height; y++ {
			for x := 0; x < p.width; x++ {
				r, _, _, _ := i.At(x, y).RGBA()
				p.qaPixels[y*p.width+x] = int32(r)
			}
		}
	default:
		return nil
	}
	return nil
}

func qaFilter(qa int32) bool {
	return qa >= 0 && (qa&0b11111) == 0
}

// --------------------------------------------------------------------------
// Band reading
// --------------------------------------------------------------------------

func (p *GeoTIFFParser) readBand(band string) ([]Record, error) {
	bandPath := filepath.Join(p.SceneDir, band+".tif")
	if _, err := os.Stat(bandPath); err != nil {
		return nil, err
	}
	raw, err := os.ReadFile(bandPath)
	if err != nil {
		return nil, err
	}
	img, err := tiff.Decode(bytes.NewReader(raw))
	if err != nil {
		return nil, fmt.Errorf("tiff decode %s: %w", bandPath, err)
	}
	gt := parseTIFFGeotransform(raw)
	bounds := img.Bounds()
	actualW := bounds.Dx()
	actualH := bounds.Dy()

	vals := extractFloats(img)
	scale, offset := bandScaleOffset(band)
	bandName := bandNameMapping(band)
	ts := atomicTS(p.Timestamp)

	qaw, qah := 0, 0
	if p.qaPixels != nil {
		qaw = p.width
		qah = p.height
	}

	records := make([]Record, 0, len(vals))
	for idx, v := range vals {
		row := idx / actualW
		col := idx % actualW

		lon := gt.xOrigin + (float64(col) + 0.5) * gt.xPixelSize
		lat := gt.yOrigin + (float64(row) + 0.5) * gt.yPixelSize

		if !isFinite(lat) || !isFinite(lon) {
			continue
		}
		if v == 0 || !isFinite(v) {
			continue
		}
		// QA filter with resolution matching
		if qaw > 0 && qah > 0 {
			qar := row * qah / actualH
			qac := col * qaw / actualW
			if qar >= qah {
				qar = qah - 1
			}
			if qac >= qaw {
				qac = qaw - 1
			}
			if qar < 0 || qar >= len(p.qaPixels) / qaw {
				continue
			}
			if !qaFilter(p.qaPixels[qar*qaw+qac]) {
				continue
			}
		}
		scaledV := v * scale + offset
		if !isFinite(scaledV) {
			continue
		}
		records = append(records, Record{
			TileID:    p.SceneID,
			Lat:       roundTo(lat, 4),
			Lon:       roundTo(lon, 4),
			Band:      bandName,
			Value:     roundTo(scaledV, 6),
			Timestamp: ts,
			LULCClass: p.LULCClass,
		})
	}
	return records, nil
}

// readBandStreaming is identical to readBand but writes each valid record
// directly to the parquet writer instead of accumulating them. This keeps
// peak memory at ~1 TIFF image + 1 float64 pixel array instead of the full
// Record slice.
func (p *GeoTIFFParser) readBandStreaming(band string, sw *ParquetStreamWriter) (int64, error) {
	bandPath := filepath.Join(p.SceneDir, band+".tif")
	if _, err := os.Stat(bandPath); err != nil {
		return 0, err
	}
	raw, err := os.ReadFile(bandPath)
	if err != nil {
		return 0, err
	}
	img, err := tiff.Decode(bytes.NewReader(raw))
	if err != nil {
		return 0, fmt.Errorf("tiff decode %s: %w", bandPath, err)
	}
	gt := parseTIFFGeotransform(raw)
	bounds := img.Bounds()
	actualW := bounds.Dx()
	actualH := bounds.Dy()

	vals := extractFloats(img)
	scale, offset := bandScaleOffset(band)
	bandName := bandNameMapping(band)
	ts := atomicTS(p.Timestamp)

	qaw, qah := 0, 0
	if p.qaPixels != nil {
		qaw = p.width
		qah = p.height
	}

	var count int64
	for idx, v := range vals {
		row := idx / actualW
		col := idx % actualW

		lon := gt.xOrigin + (float64(col) + 0.5) * gt.xPixelSize
		lat := gt.yOrigin + (float64(row) + 0.5) * gt.yPixelSize

		if !isFinite(lat) || !isFinite(lon) {
			continue
		}
		if v == 0 || !isFinite(v) {
			continue
		}
		if qaw > 0 && qah > 0 {
			qar := row * qah / actualH
			qac := col * qaw / actualW
			if qar >= qah {
				qar = qah - 1
			}
			if qac >= qaw {
				qac = qaw - 1
			}
			if qar < 0 || qar >= len(p.qaPixels)/qaw {
				continue
			}
			if !qaFilter(p.qaPixels[qar*qaw+qac]) {
				continue
			}
		}
		scaledV := v * scale + offset
		if !isFinite(scaledV) {
			continue
		}
		if err := sw.Write(Record{
			TileID:    p.SceneID,
			Lat:       roundTo(lat, 4),
			Lon:       roundTo(lon, 4),
			Band:      bandName,
			Value:     roundTo(scaledV, 6),
			Timestamp: ts,
			LULCClass: p.LULCClass,
		}); err != nil {
			return count, fmt.Errorf("write record: %w", err)
		}
		count++
	}
	return count, nil
}

// --------------------------------------------------------------------------
// UTM→WGS84 reprojection
// --------------------------------------------------------------------------

// WGS84 ellipsoid constants
const (
	wgs84A = 6378137.0           // semi-major axis
	wgs84F = 1.0 / 298.257223563 // flattening
)

var (
	wgs84E  float64 // first eccentricity squared
	wgs84E2 float64 // second eccentricity squared
)

func init() {
	wgs84E = 2*wgs84F - wgs84F*wgs84F
	wgs84E2 = wgs84E / (1 - wgs84E)
}

// --------------------------------------------------------------------------
// Geotransform parser
// --------------------------------------------------------------------------

const (
	tagModelTiePoint   = 33922
	tagModelPixelScale = 33550
	tagGeoAsciiParams  = 34737
)

type geotransform struct {
	xOrigin, yOrigin      float64
	xPixelSize, yPixelSize float64
	utmZone                float64 // 0 = already lat/lon
}

func parseTIFFGeotransform(raw []byte) geotransform {
	gt := geotransform{
		xPixelSize: 0.01,
		yPixelSize: -0.01,
	}
	if len(raw) < 8 {
		return gt
	}
	var bo binary.ByteOrder
	bo = binary.LittleEndian
	if raw[0] == 0x4D && raw[1] == 0x4D {
		bo = binary.BigEndian
	} else if raw[0] != 0x49 || raw[1] != 0x49 {
		return gt
	}
	magic := bo.Uint16(raw[2:4])
	if magic != 42 {
		return gt
	}
	ifdOffset := int(bo.Uint32(raw[4:8]))
	if ifdOffset <= 0 || ifdOffset >= len(raw) {
		return gt
	}
	numTags := bo.Uint16(raw[ifdOffset:])
	pos := ifdOffset + 2
	for i := 0; i < int(numTags); i++ {
		if pos+12 > len(raw) {
			break
		}
		tagID := bo.Uint16(raw[pos:])
		// dataType := bo.Uint16(raw[pos+2:pos+4])
		count := bo.Uint32(raw[pos+4:pos+8])
		valueOffset := bo.Uint32(raw[pos+8:pos+12])

		switch tagID {
		case tagModelTiePoint:
			off := int(valueOffset)
			if off < 0 || off+48 > len(raw) {
				break
			}
			gt.xOrigin = math.Float64frombits(bo.Uint64(raw[off+24:off+32]))
			gt.yOrigin = math.Float64frombits(bo.Uint64(raw[off+32:off+40]))
		case tagModelPixelScale:
			off := int(valueOffset)
			if off < 0 || off+24 > len(raw) {
				break
			}
			gt.xPixelSize = math.Float64frombits(bo.Uint64(raw[off:off+8]))
			pY := math.Float64frombits(bo.Uint64(raw[off+8:off+16]))
			if pY > 0 {
				pY = -pY
			}
			gt.yPixelSize = pY
		case tagGeoAsciiParams:
			off := int(valueOffset)
			n := int(count)
			if off >= 0 && off+n <= len(raw) {
				s := string(raw[off : off+n])
				gt.utmZone = parseUTMZoneFromASCII(s)
			}
		}
		pos += 12
	}
	return gt
}

// parseUTMZoneFromASCII extracts the UTM zone number from a GeoTIFF citation
// string like "WGS 84 / UTM zone 44N|WGS 84|\0". Returns 0 if not found.
func parseUTMZoneFromASCII(s string) float64 {
	const prefix = "UTM zone "
	idx := strings.Index(s, prefix)
	if idx < 0 {
		return 0
	}
	rest := s[idx+len(prefix):]
	var zone int
	for _, c := range rest {
		if c >= '0' && c <= '9' {
			zone = zone*10 + int(c-'0')
		} else {
			break
		}
	}
	return float64(zone)
}

// --------------------------------------------------------------------------
// Value extraction
// --------------------------------------------------------------------------

func extractFloats(img image.Image) []float64 {
	switch i := img.(type) {
	case *image.Gray:
		out := make([]float64, len(i.Pix))
		for k, v := range i.Pix {
			out[k] = float64(v)
		}
		return out
	case *image.Gray16:
		out := make([]float64, len(i.Pix)/2)
		for k := 0; k < len(i.Pix); k += 2 {
			out[k/2] = float64(uint16(i.Pix[k])<<8 | uint16(i.Pix[k+1]))
		}
		return out
	case *image.NRGBA:
		w := i.Bounds().Dx()
		h := i.Bounds().Dy()
		out := make([]float64, w*h)
		for y := 0; y < h; y++ {
			for x := 0; x < w; x++ {
				p := y*i.Stride + x*4
				out[y*w+x] = float64(i.Pix[p])
			}
		}
		return out
	case *image.RGBA:
		w := i.Bounds().Dx()
		h := i.Bounds().Dy()
		out := make([]float64, w*h)
		for y := 0; y < h; y++ {
			for x := 0; x < w; x++ {
				p := y*i.Stride + x*4
				out[y*w+x] = float64(i.Pix[p])
			}
		}
		return out
	default:
		return nil
	}
}

// --------------------------------------------------------------------------
// Helpers
// --------------------------------------------------------------------------

func bandNameMapping(key string) string {
	m := map[string]string{
		"B2": "B2_Blue", "B3": "B3_Green", "B4": "B4_Red",
		"B5": "B5_NIR", "B6": "B6_SWIR1",
		"B10": "B10_TIR", "B11": "B11_TIR", "ST_B10": "ST_B10",
	}
	if v, ok := m[key]; ok {
		return v
	}
	return key
}

func bandScaleOffset(band string) (scale, offset float64) {
	switch band {
	case "B4", "B5", "B6":
		return 0.0000275, -0.1
	case "B2", "B3":
		return 0.0000275, -0.1
	case "B10", "B11":
		return 0.0000275, -0.1
	case "ST_B10":
		return 0.00341802, 149.0
	default:
		return 1.0, 0.0
	}
}

func atomicTS(t time.Time) int64 {
	if t.IsZero() {
		return time.Date(2000, 1, 1, 0, 0, 0, 0, time.UTC).UnixMilli()
	}
	return t.UnixMilli()
}

func roundTo(f float64, decimals int) float64 {
	pow := math.Pow(10, float64(decimals))
	return math.Round(f*pow) / pow
}

func isFinite(f float64) bool {
	return !math.IsInf(f, 0) && !math.IsNaN(f)
}
