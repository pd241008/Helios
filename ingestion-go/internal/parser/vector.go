package parser

import (
	"encoding/binary"
	"encoding/json"
	"fmt"
	"io"
	"math"
	"os"
	"strings"
)

// ──────────────────────────────────────────────
//  Shapefile reader (pure Go, no CGO / GEOS)
// ──────────────────────────────────────────────

// shpHeader is the 100-byte fixed header of a .shp file.
type shpHeader struct {
	FileCode   int32  // big-endian, must be 9994
	Unused     [5]int32
	FileLength int32  // big-endian, 16-bit words
	Version    int32  // little-endian, must be 1000
	ShapeType  int32  // little-endian
	XMin, YMin float64
	XMax, YMax float64
	ZMin, ZMax float64
	MMin, MMax float64
}

type shpRecord struct {
	RecordNumber int32 // big-endian
	ContentLength int32 // big-endian, 16-bit words
	ShapeType    int32 // little-endian
}

// shapeType constants
const (
	stNull      = 0
	stPoint     = 1
	stPolyLine  = 3
	stPolygon   = 5
	stMultiPoint = 8
)

// parseSHP reads geometry from a .shp file and returns centroids per feature.
func parseSHP(r io.ReadSeeker) ([][2]float64, error) {
	var hdr shpHeader
	if err := binary.Read(r, binary.BigEndian, &hdr.FileCode); err != nil {
		return nil, fmt.Errorf("read shp file code: %w", err)
	}
	if hdr.FileCode != 9994 {
		return nil, fmt.Errorf("not a shapefile (file code %d)", hdr.FileCode)
	}
	// skip to byte 28 (big-endian fields before version)
	if _, err := r.Seek(28, io.SeekStart); err != nil {
		return nil, fmt.Errorf("seek to version: %w", err)
	}
	if err := binary.Read(r, binary.LittleEndian, &hdr.Version); err != nil {
		return nil, fmt.Errorf("read version: %w", err)
	}
	if hdr.Version != 1000 {
		return nil, fmt.Errorf("unsupported shapefile version %d", hdr.Version)
	}
	if err := binary.Read(r, binary.LittleEndian, &hdr.ShapeType); err != nil {
		return nil, fmt.Errorf("read shape type: %w", err)
	}
	if err := binary.Read(r, binary.LittleEndian, &hdr.XMin); err != nil {
		return nil, fmt.Errorf("read xmin: %w", err)
	}
	if err := binary.Read(r, binary.LittleEndian, &hdr.YMin); err != nil {
		return nil, fmt.Errorf("read ymin: %w", err)
	}
	if err := binary.Read(r, binary.LittleEndian, &hdr.XMax); err != nil {
		return nil, fmt.Errorf("read xmax: %w", err)
	}
	if err := binary.Read(r, binary.LittleEndian, &hdr.YMax); err != nil {
		return nil, fmt.Errorf("read ymax: %w", err)
	}
	// skip remaining header bytes (z/m ranges, 32 bytes)
	if _, err := r.Seek(100, io.SeekStart); err != nil {
		return nil, fmt.Errorf("seek past header: %w", err)
	}

	var centroids [][2]float64

	for {
		var rec shpRecord
		if err := binary.Read(r, binary.BigEndian, &rec.RecordNumber); err != nil {
			if err == io.EOF {
				break
			}
			return nil, fmt.Errorf("read record header: %w", err)
		}
		if err := binary.Read(r, binary.BigEndian, &rec.ContentLength); err != nil {
			return nil, fmt.Errorf("read content length: %w", err)
		}
		if err := binary.Read(r, binary.LittleEndian, &rec.ShapeType); err != nil {
			return nil, fmt.Errorf("read shape type: %w", err)
		}

		switch rec.ShapeType {
		case stNull:
			continue
		case stPoint:
			c, err := readPoint(r)
			if err != nil {
				return nil, err
			}
			centroids = append(centroids, c)
		case stPolygon, stPolyLine:
			c, err := readPolygonCentroid(r)
			if err != nil {
				return nil, err
			}
			centroids = append(centroids, c)
		case stMultiPoint:
			c, err := readMultiPointCentroid(r)
			if err != nil {
				return nil, err
			}
			centroids = append(centroids, c)
		default:
			// skip unknown shape types: seek past content
			contentBytes := int64(rec.ContentLength) * 2
			if _, err := r.Seek(contentBytes-4, io.SeekCurrent); err != nil {
				return nil, fmt.Errorf("skip unknown type %d: %w", rec.ShapeType, err)
			}
		}
	}

	if len(centroids) == 0 {
		return nil, fmt.Errorf("no features found in shapefile")
	}
	return centroids, nil
}

func readPoint(r io.Reader) ([2]float64, error) {
	var x, y float64
	if err := binary.Read(r, binary.LittleEndian, &x); err != nil {
		return [2]float64{}, fmt.Errorf("read point x: %w", err)
	}
	if err := binary.Read(r, binary.LittleEndian, &y); err != nil {
		return [2]float64{}, fmt.Errorf("read point y: %w", err)
	}
	return [2]float64{x, y}, nil
}

func readPolygonCentroid(r io.Reader) ([2]float64, error) {
	// Skip bbox (4 × float64 = 32 bytes)
	if _, err := io.CopyN(io.Discard, r, 32); err != nil {
		return [2]float64{}, fmt.Errorf("skip bbox: %w", err)
	}
	var numParts, numPoints int32
	if err := binary.Read(r, binary.LittleEndian, &numParts); err != nil {
		return [2]float64{}, fmt.Errorf("read numParts: %w", err)
	}
	if err := binary.Read(r, binary.LittleEndian, &numPoints); err != nil {
		return [2]float64{}, fmt.Errorf("read numPoints: %w", err)
	}
	if numParts <= 0 || numPoints <= 0 {
		if _, err := io.CopyN(io.Discard, r, int64(numPoints)*16); err != nil {
			return [2]float64{}, err
		}
		return [2]float64{0, 0}, nil
	}

	// Read part indices (we only need the first ring — exterior ring)
	parts := make([]int32, numParts)
	if err := binary.Read(r, binary.LittleEndian, &parts); err != nil {
		return [2]float64{}, fmt.Errorf("read parts: %w", err)
	}

	// Determine the range of points in the first ring (exterior).
	ringStart := parts[0]
	var ringEnd int32 = numPoints
	if numParts > 1 {
		ringEnd = parts[1]
	}
	nRingPts := ringEnd - ringStart

	// Skip to the first point of the exterior ring.
	skipBytes := int64(ringStart) * 16
	if _, err := io.CopyN(io.Discard, r, skipBytes); err != nil {
		return [2]float64{}, fmt.Errorf("skip to ring start: %w", err)
	}

	// Average the ring points.
	var cx, cy float64
	for i := int32(0); i < nRingPts; i++ {
		var x, y float64
		if err := binary.Read(r, binary.LittleEndian, &x); err != nil {
			return [2]float64{}, fmt.Errorf("read point %d: %w", i, err)
		}
		if err := binary.Read(r, binary.LittleEndian, &y); err != nil {
			return [2]float64{}, fmt.Errorf("read point %d y: %w", i, err)
		}
		cx += x
		cy += y
	}
	if nRingPts > 0 {
		cx /= float64(nRingPts)
		cy /= float64(nRingPts)
	}

	return [2]float64{cx, cy}, nil
}

func readMultiPointCentroid(r io.Reader) ([2]float64, error) {
	// Skip bbox (32 bytes)
	if _, err := io.CopyN(io.Discard, r, 32); err != nil {
		return [2]float64{}, fmt.Errorf("skip bbox: %w", err)
	}
	var numPoints int32
	if err := binary.Read(r, binary.LittleEndian, &numPoints); err != nil {
		return [2]float64{}, fmt.Errorf("read numPoints: %w", err)
	}
	if numPoints <= 0 {
		return [2]float64{0, 0}, nil
	}
	var cx, cy float64
	for i := int32(0); i < numPoints; i++ {
		var x, y float64
		if err := binary.Read(r, binary.LittleEndian, &x); err != nil {
			return [2]float64{}, fmt.Errorf("read point %d: %w", i, err)
		}
		if err := binary.Read(r, binary.LittleEndian, &y); err != nil {
			return [2]float64{}, fmt.Errorf("read point %d y: %w", i, err)
		}
		cx += x
		cy += y
	}
	cx /= float64(numPoints)
	cy /= float64(numPoints)
	return [2]float64{cx, cy}, nil
}

// ──────────────────────────────────────────────
//  DBF reader (dBase III, minimal attribute extract)
// ──────────────────────────────────────────────

type dbfField struct {
	Name    [11]byte
	Type    byte
	Address [4]byte
	Length  byte
	Decimal byte
}

const dbfHeaderSize = 32

func parseDBF(r io.Reader) ([]string, error) {
	// Read header.
	var version byte
	if err := binary.Read(r, binary.LittleEndian, &version); err != nil {
		return nil, fmt.Errorf("read dbf version: %w", err)
	}
	var lastUpdate [3]byte
	if err := binary.Read(r, binary.LittleEndian, &lastUpdate); err != nil {
		return nil, fmt.Errorf("read dbf date: %w", err)
	}
	var numRecords int32
	if err := binary.Read(r, binary.LittleEndian, &numRecords); err != nil {
		return nil, fmt.Errorf("read numRecords: %w", err)
	}
	var headerLen int16
	if err := binary.Read(r, binary.LittleEndian, &headerLen); err != nil {
		return nil, fmt.Errorf("read headerLen: %w", err)
	}
	var recordLen int16
	if err := binary.Read(r, binary.LittleEndian, &recordLen); err != nil {
		return nil, fmt.Errorf("read recordLen: %w", err)
	}
	// skip remaining 16 bytes of header
	if _, err := io.CopyN(io.Discard, r, 16); err != nil {
		return nil, fmt.Errorf("skip header padding: %w", err)
	}

	// Read field descriptors (each 32 bytes, terminated by 0x0D).
	numFields := (int(headerLen) - dbfHeaderSize - 1) / dbfHeaderSize
	fields := make([]dbfField, numFields)
	for i := range numFields {
		if err := binary.Read(r, binary.LittleEndian, &fields[i]); err != nil {
			return nil, fmt.Errorf("read field %d: %w", i, err)
		}
	}
	// Field terminator (0x0D)
	var term byte
	if err := binary.Read(r, binary.LittleEndian, &term); err != nil {
		return nil, fmt.Errorf("read field terminator: %w", err)
	}

	// Pick the first string-like field as the LULC class.
	fieldIdx := -1
	fieldLen := 0
	for i, f := range fields {
		if f.Type == 'C' || f.Type == 'N' { // Character or Numeric
			fieldIdx = i
			fieldLen = int(f.Length)
			break
		}
	}
	if fieldIdx < 0 {
		return nil, nil // no usable attributes
	}

	// Read all records and extract the chosen attribute.
	records := make([]string, 0, numRecords)
	buf := make([]byte, recordLen)
	for i := int32(0); i < numRecords; i++ {
		if _, err := io.ReadFull(r, buf); err != nil {
			return nil, fmt.Errorf("read dbf record %d: %w", i, err)
		}
		start := 1 // skip deletion flag
		for f := range fieldIdx {
			start += int(fields[f].Length)
		}
		end := start + fieldLen
		if end > len(buf) {
			end = len(buf)
		}
		val := strings.TrimSpace(string(buf[start:end]))
		if val == "" {
			val = "unknown"
		}
		records = append(records, val)
	}
	return records, nil
}

// ──────────────────────────────────────────────
//  Public API
// ──────────────────────────────────────────────

// ParseShapefile reads a .shp file (with sibling .dbf) and returns
// Records with centroids and LULC class labels extracted from the
// first character or numeric attribute column.
func ParseShapefile(shpPath, sourceID string) ([]Record, error) {
	shpFile, err := os.Open(shpPath)
	if err != nil {
		return nil, fmt.Errorf("open shp: %w", err)
	}
	defer shpFile.Close()

	centroids, err := parseSHP(shpFile)
	if err != nil {
		return nil, fmt.Errorf("parse shp: %w", err)
	}

	// Attempt to read attributes from the sibling .dbf file.
	var attrs []string
	dbfPath := strings.TrimSuffix(shpPath, ".shp") + ".dbf"
	if dbfFile, err := os.Open(dbfPath); err == nil {
		defer dbfFile.Close()
		attrs, err = parseDBF(dbfFile)
		if err != nil {
			attrs = nil
		}
	}

	records := make([]Record, 0, len(centroids))
	for i, c := range centroids {
		if math.IsInf(c[0], 0) || math.IsNaN(c[0]) ||
			math.IsInf(c[1], 0) || math.IsNaN(c[1]) {
			continue
		}
		cls := "unknown"
		if i < len(attrs) && attrs[i] != "" {
			cls = attrs[i]
		}
		records = append(records, Record{
			TileID:    sourceID,
			Lat:       c[1],
			Lon:       c[0],
			Band:      "lulc_class",
			Value:     1.0,
			Timestamp: 0,
			LULCClass: cls,
		})
	}
	return records, nil
}

// ParseGeoJSON parses a GeoJSON FeatureCollection and returns Records
// with centroids and LULC class labels extracted from feature properties.
func ParseGeoJSON(data []byte, sourceID string) ([]Record, error) {
	var fc struct {
		Type     string `json:"type"`
		Features []struct {
			Type       string         `json:"type"`
			Properties map[string]any `json:"properties"`
			Geometry   struct {
				Type        string          `json:"type"`
				Coordinates json.RawMessage `json:"coordinates"`
			} `json:"geometry"`
		} `json:"features"`
	}

	if err := json.Unmarshal(data, &fc); err != nil {
		return nil, fmt.Errorf("parse geojson: %w", err)
	}
	if fc.Type != "FeatureCollection" {
		return nil, fmt.Errorf("expected FeatureCollection, got %q", fc.Type)
	}

	var records []Record
	for i, feat := range fc.Features {
		centroid, ok := geoJSONCentroid(feat.Geometry.Type, feat.Geometry.Coordinates)
		if !ok {
			continue
		}
		if math.IsInf(centroid[0], 0) || math.IsNaN(centroid[0]) ||
			math.IsInf(centroid[1], 0) || math.IsNaN(centroid[1]) {
			continue
		}
		cls := extractLULCClass(feat.Properties)
		if cls == "" {
			cls = "unknown"
		}
		records = append(records, Record{
			TileID:    fmt.Sprintf("%s_%d", sourceID, i),
			Lat:       centroid[1],
			Lon:       centroid[0],
			Band:      "lulc_class",
			Value:     1.0,
			Timestamp: 0,
			LULCClass: cls,
		})
	}
	return records, nil
}

// ──────────────────────────────────────────────
//  GeoJSON helpers
// ──────────────────────────────────────────────

func geoJSONCentroid(geomType string, coords json.RawMessage) ([2]float64, bool) {
	switch geomType {
	case "Point":
		var pt []float64
		if json.Unmarshal(coords, &pt) == nil && len(pt) >= 2 {
			return [2]float64{pt[0], pt[1]}, true
		}
	case "MultiPoint":
		var pts []any
		if json.Unmarshal(coords, &pts) != nil {
			return [2]float64{}, false
		}
		return avgCoords(pts)
	case "Polygon":
		var rings []any
		if json.Unmarshal(coords, &rings) != nil || len(rings) == 0 {
			return [2]float64{}, false
		}
		ring, ok := rings[0].([]any)
		if !ok {
			return [2]float64{}, false
		}
		return avgCoords(ring)
	case "MultiPolygon":
		var polys []any
		if json.Unmarshal(coords, &polys) != nil {
			return [2]float64{}, false
		}
		var all []any
		for _, p := range polys {
			rings, ok := p.([]any)
			if !ok || len(rings) == 0 {
				continue
			}
			ring, ok := rings[0].([]any)
			if !ok {
				continue
			}
			all = append(all, ring...)
		}
		return avgCoords(all)
	}
	return [2]float64{}, false
}

func avgCoords(pts []any) ([2]float64, bool) {
	var cx, cy float64
	var n int
	for _, p := range pts {
		c, ok := p.([]any)
		if !ok || len(c) < 2 {
			continue
		}
		x, _ := c[0].(float64)
		y, _ := c[1].(float64)
		cx += x
		cy += y
		n++
	}
	if n > 0 {
		return [2]float64{cx / float64(n), cy / float64(n)}, true
	}
	return [2]float64{}, false
}

// extractLULCClass tries common property keys for a land‑use label.
func extractLULCClass(props map[string]any) string {
	candidates := []string{
		"lulc_class", "lulc", "class", "type", "landuse",
		"category", "lu_code", "description", "name", "label",
	}
	for _, c := range candidates {
		if v, ok := props[c]; ok {
			if s, ok := v.(string); ok && s != "" {
				return s
			}
		}
	}
	return "unknown"
}
