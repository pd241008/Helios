package parser

import (
	"math"
	"os"
	"path/filepath"
	"testing"
	"time"
)

// TestBandNameMapping verifies the standardization of band key names.
func TestBandNameMapping(t *testing.T) {
	tests := []struct {
		input    string
		expected string
	}{
		{"B2", "B2_Blue"},
		{"B4", "B4_Red"},
		{"B5", "B5_NIR"},
		{"B10", "B10_TIR"},
		{"B11", "B11_TIR"},
		{"ST_B10", "ST_B10"},
		{"UNKNOWN", "UNKNOWN"},
		{"B6", "B6_SWIR1"},
	}
	for _, tt := range tests {
		result := bandNameMapping(tt.input)
		if result != tt.expected {
			t.Errorf("bandNameMapping(%q) = %q; want %q", tt.input, result, tt.expected)
		}
	}
}

// TestBandScaleOffset verifies the scale/offset values per band.
func TestBandScaleOffset(t *testing.T) {
	tests := []struct {
		band         string
		expScale     float64
		expOffset    float64
		expFinite    bool
	}{
		{"ST_B10", 0.00341802, 149.0, true},
		{"B10", 0.0000275, -0.1, true},
		{"B11", 0.0000275, -0.1, true},
		{"B5", 0.0000275, -0.1, true},
		{"B4", 0.0000275, -0.1, true},
		{"B3", 0.0000275, -0.1, true},
		{"B2", 0.0000275, -0.1, true},
		{"B6", 0.0000275, -0.1, true},
		{"OTHER", 1.0, 0.0, true},
	}
	for _, tt := range tests {
		s, o := bandScaleOffset(tt.band)
		if math.Abs(s-tt.expScale) > 1e-6 || math.Abs(o-tt.expOffset) > 1e-6 {
			t.Errorf("bandScaleOffset(%q) = (%f, %f); want (%f, %f)",
				tt.band, s, o, tt.expScale, tt.expOffset)
		}
		if !isFinite(s) || !isFinite(o) {
			t.Errorf("bandScaleOffset(%q) returned non-finite values", tt.band)
		}
	}
}

// TestQAFilter ensures the bitwise cloud/fill filtering works as expected.
func TestQAFilter(t *testing.T) {
	tests := []struct {
		qa      int32
		valid   bool
	}{
	{0, true},   // clear
	{32, true},  // bit 5 (reserved / unused)
	{1, false},  // bit 0 - fill
		{8, false},  // bit 3 - cloud
		{4, false},  // bit 2 - cirrus
		{2, false},  // bit 1 - dilated cloud
		{15, false}, // bits 0-3 fill+cloud
		{31, false}, // bits 0-4 all set
	}
	for _, tt := range tests {
		result := qaFilter(tt.qa)
		if result != tt.valid {
			t.Errorf("qaFilter(%d) = %v; want %v", tt.qa, result, tt.valid)
		}
	}
}

// TestRoundTo verifies the rounding helper.
func TestRoundTo(t *testing.T) {
	if result := roundTo(123.456789, 2); result != 123.46 {
		t.Errorf("roundTo(123.456789, 2) = %f; want 123.46", result)
	}
	if result := roundTo(123.456789, 4); result != 123.4568 {
		t.Errorf("roundTo(123.456789, 4) = %f; want 123.4568", result)
	}
	if result := roundTo(0.9999, 0); result != 1.0 {
		t.Errorf("roundTo(0.9999, 0) = %f; want 1.0", result)
	}
}

// TestAtomicTS verifies the timestamp helper.
func TestAtomicTS(t *testing.T) {
	// Zero time
	t1 := time.Time{}
	result1 := atomicTS(t1)
	if result1 <= 0 {
		t.Errorf("atomicTS(zero) = %d; want positive", result1)
	}

	// Specific time
	t2 := time.Date(2024, 3, 1, 10, 30, 0, 0, time.UTC)
	result2 := atomicTS(t2)
	expected := int64(1709289000000)
	if result2 != expected {
		t.Errorf("atomicTS(2024-03-01T10:30:00Z) = %d; want %d", result2, expected)
	}
}

// TestRoundTripGeoTIFFUnavailablePath verifies that a non-existent scene
// directory produces no errors from loading Records().
func TestGeoTIFFParserMissingSceneDir(t *testing.T) {
	tmpDir := t.TempDir()
	nonexistentDir := filepath.Join(tmpDir, "nonexistent")
	parser_impl := NewGeoTIFFParser("test_scene", nonexistentDir, time.Now())
	records, err := parser_impl.Records()
	if err != nil {
		t.Fatalf("Records() on nonexistent dir returned error: %v", err)
	}
	if len(records) != 0 {
		t.Errorf("Records() returned %d records; want 0 (no GeoTIFFs)", len(records))
	}
}

// TestGeoTIFFParserEmptySceneDir verifies that an empty scene directory
// produces no records but also no errors.
func TestGeoTIFFParserEmptySceneDir(t *testing.T) {
	tmpDir := t.TempDir()
	sceneDir := tmpDir
	os.MkdirAll(sceneDir, 0755)
	parser_impl := NewGeoTIFFParser("test_empty", sceneDir, time.Now())
	records, err := parser_impl.Records()
	if err != nil {
		t.Fatalf("Records() on empty dir returned error: %v", err)
	}
	if len(records) != 0 {
		t.Errorf("Records() returned %d records; want 0", len(records))
	}
}

// TestParseTIFFGeotransform validates that the geotransform parser returns
// sensible default values for non-TIFF data (no errors).
func TestParseTIFFGeotransformDefaults(t *testing.T) {
	// A too-small byte slice should return defaults
	gt := parseTIFFGeotransform([]byte{0, 0})
	if gt.xPixelSize != 0.01 || math.Abs(gt.yPixelSize) != 0.01 {
		t.Errorf("parseTIFFGeotransform(too_short) returned (%f, %f); want (0.01, 0.01)",
			gt.xPixelSize, gt.yPixelSize)
	}

	// Non-TIFF data returns defaults
	gt2 := parseTIFFGeotransform([]byte("AAAAAAAABBBBBBBBCCCCCCCCDDDDDDDD"))
	if gt2.xPixelSize != 0.01 {
		t.Errorf("default xPixelSize = %f; want 0.01", gt2.xPixelSize)
	}
}

// TestextractFloatsNil tests that an unsupported image type returns nil.
func TestExtractFloatsUnsupportedType(t *testing.T) {
	// Create a simple non-image to test the default case
	result := extractFloats(nil)
	if result != nil {
		t.Errorf("extractFloats(nil) = %v; want nil", result)
	}
}
