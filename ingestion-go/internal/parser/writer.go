package parser

import (
	"fmt"
	"io"
	"os"
	"path/filepath"

	"github.com/apache/arrow-go/v18/arrow"
	"github.com/apache/arrow-go/v18/arrow/array"
	"github.com/apache/arrow-go/v18/arrow/memory"
	"github.com/apache/arrow-go/v18/parquet"
	"github.com/apache/arrow-go/v18/parquet/compress"
	"github.com/apache/arrow-go/v18/parquet/pqarrow"
)

var recordSchema = arrow.NewSchema([]arrow.Field{
	{Name: "tile_id", Type: arrow.BinaryTypes.String},
	{Name: "lat", Type: arrow.PrimitiveTypes.Float64},
	{Name: "lon", Type: arrow.PrimitiveTypes.Float64},
	{Name: "band", Type: arrow.BinaryTypes.String},
	{Name: "value", Type: arrow.PrimitiveTypes.Float64},
	{Name: "timestamp", Type: arrow.FixedWidthTypes.Timestamp_ms},
	{Name: "lulc_class", Type: arrow.BinaryTypes.String},
}, nil)

// WriteRecords serialises a slice of Record into a Parquet file at path.
// Deprecated: use ParquetStreamWriter for large datasets to avoid OOM.
func WriteRecords(path string, records []Record) error {
	sw, err := NewParquetStreamWriter(path)
	if err != nil {
		return err
	}
	for i := range records {
		if err := sw.Write(records[i]); err != nil {
			sw.Close()
			return err
		}
	}
	return sw.Close()
}

// ParquetStreamWriter opens a parquet file and accepts records one at a time.
type ParquetStreamWriter struct {
	fw      io.Closer
	writer  *pqarrow.FileWriter
	bldr    *array.RecordBuilder
	path    string
	records []Record
}

// NewParquetStreamWriter creates a streaming writer for Record values.
func NewParquetStreamWriter(path string) (*ParquetStreamWriter, error) {
	if err := os.MkdirAll(filepath.Dir(path), 0o750); err != nil {
		return nil, fmt.Errorf("mkdir %s: %w", filepath.Dir(path), err)
	}
	f, err := os.Create(path)
	if err != nil {
		return nil, fmt.Errorf("create parquet file %s: %w", path, err)
	}

	props := parquet.NewWriterProperties(
		parquet.WithCompression(compress.Codecs.Snappy),
	)
	arrProps := pqarrow.DefaultWriterProps()

	w, err := pqarrow.NewFileWriter(recordSchema, f, props, arrProps)
	if err != nil {
		f.Close()
		return nil, fmt.Errorf("init parquet writer: %w", err)
	}

	bldr := array.NewRecordBuilder(memory.DefaultAllocator, recordSchema)

	return &ParquetStreamWriter{
		fw:      f,
		writer:  w,
		bldr:    bldr,
		path:    path,
		records: make([]Record, 0, 8192),
	}, nil
}

// Write appends a single record to the parquet file buffer, flushing as needed.
func (s *ParquetStreamWriter) Write(rec Record) error {
	s.records = append(s.records, rec)
	if len(s.records) >= 8192 {
		return s.flush()
	}
	return nil
}

func (s *ParquetStreamWriter) flush() error {
	if len(s.records) == 0 {
		return nil
	}

	b0 := s.bldr.Field(0).(*array.StringBuilder)
	b1 := s.bldr.Field(1).(*array.Float64Builder)
	b2 := s.bldr.Field(2).(*array.Float64Builder)
	b3 := s.bldr.Field(3).(*array.StringBuilder)
	b4 := s.bldr.Field(4).(*array.Float64Builder)
	b5 := s.bldr.Field(5).(*array.TimestampBuilder)
	b6 := s.bldr.Field(6).(*array.StringBuilder)

	for _, r := range s.records {
		b0.Append(r.TileID)
		b1.Append(r.Lat)
		b2.Append(r.Lon)
		b3.Append(r.Band)
		b4.Append(r.Value)
		b5.Append(arrow.Timestamp(r.Timestamp))
		b6.Append(r.LULCClass)
	}

	rec := s.bldr.NewRecord()
	defer rec.Release()

	if err := s.writer.Write(rec); err != nil {
		return err
	}

	s.records = s.records[:0]
	return nil
}

// Close finalises the parquet file. Must be called after all records are written.
func (s *ParquetStreamWriter) Close() error {
	if err := s.flush(); err != nil {
		s.writer.Close()
		s.fw.Close()
		return fmt.Errorf("flush remaining: %w", err)
	}
	if err := s.writer.Close(); err != nil {
		s.fw.Close()
		return fmt.Errorf("close parquet writer: %w", err)
	}
	s.fw.Close()
	return nil
}
