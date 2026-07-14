package parser

import (
	"fmt"
	"io"
	"os"

	"github.com/xitongsys/parquet-go-source/local"
	"github.com/xitongsys/parquet-go/writer"
)

// WriteRecords serialises a slice of Record into a Parquet file at path.
// Deprecated: use ParquetStreamWriter for large datasets to avoid OOM.
func WriteRecords(path string, records []Record) error {
	if err := os.MkdirAll(workingDir(path), 0o750); err != nil {
		return fmt.Errorf("mkdir %s: %w", workingDir(path), err)
	}
	fw, err := local.NewLocalFileWriter(path)
	if err != nil {
		return fmt.Errorf("create parquet file %s: %w", path, err)
	}
	defer fw.Close()

	pw, err := writer.NewParquetWriter(fw, new(Record), 1)
	if err != nil {
		return fmt.Errorf("init parquet writer: %w", err)
	}
	pw.RowGroupSize = 128 * 1024 * 1024 // 128 MB
	pw.PageSize = 8 * 1024               // 8 KB

	for i := range records {
		if err := pw.Write(records[i]); err != nil {
			return fmt.Errorf("write record %d: %w", i, err)
		}
	}

	if err := pw.WriteStop(); err != nil {
		return fmt.Errorf("finalise parquet: %w", err)
	}
	return nil
}

// ParquetStreamWriter opens a parquet file and accepts records one at a time,
// avoiding the need to hold all records in memory simultaneously.
type ParquetStreamWriter struct {
	fw   io.Closer
	pw   *writer.ParquetWriter
	path string
}

// NewParquetStreamWriter creates a streaming writer for Record values.
func NewParquetStreamWriter(path string) (*ParquetStreamWriter, error) {
	if err := os.MkdirAll(workingDir(path), 0o750); err != nil {
		return nil, fmt.Errorf("mkdir %s: %w", workingDir(path), err)
	}
	fw, err := local.NewLocalFileWriter(path)
	if err != nil {
		return nil, fmt.Errorf("create parquet file %s: %w", path, err)
	}
	pw, err := writer.NewParquetWriter(fw, new(Record), 1)
	if err != nil {
		fw.Close()
		return nil, fmt.Errorf("init parquet writer: %w", err)
	}
	pw.RowGroupSize = 128 * 1024 * 1024 // 128 MB
	pw.PageSize = 8 * 1024               // 8 KB
	return &ParquetStreamWriter{fw: fw, pw: pw, path: path}, nil
}

// Write appends a single record to the parquet file.
func (s *ParquetStreamWriter) Write(rec Record) error {
	return s.pw.Write(rec)
}

// Close finalises the parquet file. Must be called after all records are written.
func (s *ParquetStreamWriter) Close() error {
	if err := s.pw.WriteStop(); err != nil {
		s.fw.Close()
		return fmt.Errorf("finalise parquet %s: %w", s.path, err)
	}
	return s.fw.Close()
}

func workingDir(path string) string {
	idx := len(path) - 1
	for idx >= 0 && path[idx] != '/' && path[idx] != '\\' {
		idx--
	}
	if idx < 0 {
		return "."
	}
	return path[:idx]
}
