package parser

import (
	"bytes"
	"encoding/binary"
	"fmt"
	"image"
	"math"
	"os"
	"path/filepath"
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
		bandNames: []string{"B2", "B3", "B4", "B5", "B6", "B7", "ST_B10", "QA_PIXEL"},
	}
}

func (p *GeoTIFFParser) Records(pw *ParquetStreamWriter) (int64, error) {
	total := int64(0)
	if err := p.loadQA(); err != nil {
		return 0, err
	}
	for _, band := range p.bandNames {
		if band == "QA_PIXEL" {
			continue
		}
		n, err := p.writeBand(pw, band)
		if err != nil {
			continue
		}
		total += n
	}
	return total, nil
}

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

func (p *GeoTIFFParser) writeBand(pw *ParquetStreamWriter, band string) (int64, error) {
	bandPath := filepath.Join(p.SceneDir, band+".tif")
	if _, err := os.Stat(bandPath); err != nil {
		return 0, err
	}
	raw, err := os.ReadFile(bandPath)
	if err != nil {
		return 0, err
	}

	gt := parseTIFFGeotransform(raw)
	epsg := p.parseEPSG(raw)

	img, err := tiff.Decode(bytes.NewReader(raw))
	if err != nil {
		return 0, fmt.Errorf("tiff decode %s: %w", bandPath, err)
	}
	bounds := img.Bounds()
	actualW := bounds.Dx()
	actualH := bounds.Dy()

	scale, offset := bandScaleOffset(band)
	bandName := bandNameMapping(band)
	ts := atomicTS(p.Timestamp)

	qaw, qah := 0, 0
	if p.qaPixels != nil {
		qaw = p.width
		qah = p.height
	}

	var n int64
	for y := 0; y < actualH; y++ {
		for x := 0; x < actualW; x++ {
			v := pixelAt(img, x, y)
			if v == 0 || !isFinite(v) {
				continue
			}
			_ = qaw
			if qaw > 0 && qah > 0 {
				qar := y * qah / actualH
				qac := x * qaw / actualW
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

			px := gt.xOrigin + (float64(x)+0.5)*gt.xPixelSize
			py := gt.yOrigin + (float64(y)+0.5)*gt.yPixelSize

			lon, lat := reproject(epsg, 0, px, py)

			if !isFinite(lat) || !isFinite(lon) {
				continue
			}

			scaledV := v*scale + offset
			if !isFinite(scaledV) {
				continue
			}
			if err := pw.Write(Record{
				TileID:    p.SceneID,
				Lat:       roundTo(lat, 6),
				Lon:       roundTo(lon, 6),
				Band:      bandName,
				Value:     roundTo(scaledV, 6),
				Timestamp: ts,
				LULCClass: p.LULCClass,
			}); err != nil {
				return n, fmt.Errorf("write record: %w", err)
			}
			n++
		}
	}
	return n, nil
}

func pixelAt(img image.Image, x, y int) float64 {
	switch i := img.(type) {
	case *image.Gray:
		return float64(i.Pix[y*i.Stride+x])
	case *image.Gray16:
		off := y*i.Stride + x*2
		return float64(uint16(i.Pix[off])<<8 | uint16(i.Pix[off+1]))
	case *image.NRGBA:
		off := y*i.Stride + x*4
		return float64(i.Pix[off])
	case *image.RGBA:
		off := y*i.Stride + x*4
		return float64(i.Pix[off])
	default:
		r, _, _, _ := i.At(x, y).RGBA()
		return float64(r)
	}
}

// parseEPSG reads the ProjectedCSTypeGeoKey (ID 3072) from the
// GeoKeyDirectoryTag (34735) to determine the EPSG code.
func (p *GeoTIFFParser) parseEPSG(raw []byte) int {
	if len(raw) < 8 {
		return 0
	}
	bo := byteOrder(raw)
	if bo == nil {
		return 0
	}
	ifdOff := int(bo.Uint32(raw[4:8]))
	if ifdOff <= 0 || ifdOff >= len(raw) {
		return 0
	}
	numTags := bo.Uint16(raw[ifdOff:])
	pos := ifdOff + 2

	for i := 0; i < int(numTags); i++ {
		if pos+12 > len(raw) {
			break
		}
		tagID := bo.Uint16(raw[pos:])
		dtype := bo.Uint16(raw[pos+2:])
		count := bo.Uint32(raw[pos+4:])
		valOff := bo.Uint32(raw[pos+8:])

		if tagID == 34735 {
			keyDirOff := int(valOff)
			if keyDirOff < 0 || keyDirOff+8 > len(raw) {
				return 0
			}
			sz := int(dtSize(dtype)) * int(count)
			if keyDirOff+sz > len(raw) {
				return 0
			}
			numKeys := bo.Uint16(raw[keyDirOff+6:])
			for j := 0; j < int(numKeys); j++ {
				entryOff := keyDirOff + 8 + j*8
				if entryOff+8 > len(raw) {
					break
				}
				kid := bo.Uint16(raw[entryOff:])
				// tiffLoc := bo.Uint16(raw[entryOff+2:])
				// cntIdx := bo.Uint16(raw[entryOff+4:])
				valOrOff := bo.Uint16(raw[entryOff+6:])
				if kid == 3072 {
					return int(valOrOff)
				}
			}
		}
		pos += 12
	}
	return 0
}

func byteOrder(raw []byte) binary.ByteOrder {
	if raw[0] == 0x4D && raw[1] == 0x4D {
		return binary.BigEndian
	}
	if raw[0] == 0x49 && raw[1] == 0x49 {
		return binary.LittleEndian
	}
	return nil
}

func dtSize(dt uint16) uint32 {
	switch dt {
	case 1, 2, 6, 7:
		return 1
	case 3, 8:
		return 2
	case 4, 9, 11:
		return 4
	case 5, 10, 12:
		return 8
	default:
		return 1
	}
}

// reproject converts (px, py) from the source CRS to WGS84 lon/lat.
// Currently handles EPSG:326XX (UTM north) and EPSG:327XX (UTM south).
// Returns (px, py) unchanged for geographic CRS or unknown EPSG codes.
func reproject(epsg int, _, px, py float64) (lon, lat float64) {
	if epsg == 0 {
		return px, py
	}

	zone := 0
	hemiNorth := true
	if epsg >= 32601 && epsg <= 32660 {
		zone = epsg - 32600
		hemiNorth = true
	} else if epsg >= 32701 && epsg <= 32760 {
		zone = epsg - 32700
		hemiNorth = false
	} else {
		return px, py
	}

	lon0 := float64(zone)*6.0 - 183.0
	lat, lon = utmToWGS84(px, py, lon0, hemiNorth)
	return lon, lat
}

// utmToWGS84 converts UTM easting/northing to WGS84 latitude/longitude
// using transverse Mercator (EPSG 9807) with WGS84 ellipsoid.
func utmToWGS84(easting, northing, lon0Deg float64, north bool) (latDeg, lonDeg float64) {
	// WGS84 ellipsoid
	a := 6378137.0
	f := 1.0 / 298.257223563
	e2 := 2*f - f*f
	e4 := e2 * e2
	e6 := e4 * e2

	k0 := 0.9996
	fe := 500000.0
	fn := 0.0
	if !north {
		fn = 10000000.0
	}

	lon0 := lon0Deg * math.Pi / 180.0

	x := easting - fe
	y := northing - fn

	m := y / k0
	mu := m / (a * (1 - e2/4 - 3*e4/64 - 5*e6/256))

	e1 := (1 - math.Sqrt(1-e2)) / (1 + math.Sqrt(1-e2))
	phi1 := mu +
		(3*e1/2-27*e1*e1*e1/32)*math.Sin(2*mu) +
		(21*e1*e1/16-55*e1*e1*e1*e1/32)*math.Sin(4*mu) +
		(151*e1*e1*e1/96)*math.Sin(6*mu)

	t1 := math.Tan(phi1)
	t12 := t1 * t1
	c1 := e2 / (1 - e2) * math.Cos(phi1) * math.Cos(phi1)
	r1 := a * (1 - e2) / math.Pow(1-e2*math.Sin(phi1)*math.Sin(phi1), 1.5)
	n1 := a / math.Sqrt(1-e2*math.Sin(phi1)*math.Sin(phi1))
	d := x / (n1 * k0)

	lat := phi1 -
		n1*t1/r1*(d*d/2-
			(5+3*t12+10*c1-4*c1*c1-9*e2)*d*d*d*d/24+
			(61+90*t12+298*c1+45*t12*t12-252*e2-3*c1*c1)*d*d*d*d*d*d/720)
	lon := lon0 +
		(d-
			(1+2*t12+c1)*d*d*d/6+
			(5-2*c1+28*t12-3*c1*c1+8*e2+24*t12*t12)*d*d*d*d*d/120) / math.Cos(phi1)

	return lat * 180.0 / math.Pi, lon * 180.0 / math.Pi
}

const (
	tagModelTiePoint   = 33922
	tagModelPixelScale = 33550
)

type geotransform struct {
	xOrigin, yOrigin      float64
	xPixelSize, yPixelSize float64
}

func parseTIFFGeotransform(raw []byte) geotransform {
	gt := geotransform{
		xPixelSize: 0.01,
		yPixelSize: -0.01,
	}
	if len(raw) < 8 {
		return gt
	}
	bo := byteOrder(raw)
	if bo == nil {
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
		count := bo.Uint32(raw[pos+4:pos+8])
		_ = count
		valueOffset := bo.Uint32(raw[pos+8:pos+12])

		switch tagID {
		case tagModelTiePoint:
			off := int(valueOffset)
			if off < 0 || off+48 > len(raw) {
				break
			}
			gt.xOrigin = math.Float64frombits(bo.Uint64(raw[off+24 : off+32]))
			gt.yOrigin = math.Float64frombits(bo.Uint64(raw[off+32 : off+40]))
		case tagModelPixelScale:
			off := int(valueOffset)
			if off < 0 || off+24 > len(raw) {
				break
			}
			gt.xPixelSize = math.Float64frombits(bo.Uint64(raw[off : off+8]))
			pY := math.Float64frombits(bo.Uint64(raw[off+8 : off+16]))
			if pY > 0 {
				pY = -pY
			}
			gt.yPixelSize = pY
		}
		pos += 12
	}
	return gt
}

func bandNameMapping(key string) string {
	m := map[string]string{
		"B1": "B1_Coastal", "B2": "B2_Blue", "B3": "B3_Green", "B4": "B4_Red",
		"B5": "B5_NIR", "B6": "B6_SWIR1", "B7": "B7_SWIR2",
		"B10": "B10_TIR", "B11": "B11_TIR", "ST_B10": "ST_B10",
	}
	if v, ok := m[key]; ok {
		return v
	}
	return key
}

func bandScaleOffset(band string) (scale, offset float64) {
	switch band {
	case "B1", "B2", "B3", "B4", "B5", "B6", "B7":
		return 0.0000275, -0.2
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
