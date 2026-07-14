package parser

import (
	"fmt"
	"io"
	"os"

	"github.com/xitongsys/parquet-go-source/local"
	"github.com/xitongsys/parquet-go/writer"
)

// WriteRecords serialises a slice of Record into a Parquet file at path.
func WriteRecords(path string, records []Record) error {
	if err := os.MkdirAll(workingDir(path), 0o750); err != nil {
		return fmt.Errorf("mkdir %s: %w", workingDir(path), err)
	}
	fw, err := local.NewLocalFileWriter(path)
	if err != nil {
		return fmt.Errorf("create parquet file %s: %w", path, err)
	}
	defer fw.Close()

	pw, err := writer.NewParquetWriter(fw, new(Record), int64(len(records)))
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

// OpenRecordsWriter opens a Parquet file for streaming writes.
// Caller must call Close on the returned ParquetWriter after writing.
func OpenRecordsWriter(path string) (*ParquetStreamWriter, error) {
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
	pw.RowGroupSize = 128 * 1024 * 1024
	pw.PageSize = 8 * 1024
	return &ParquetStreamWriter{pw: pw, fc: fw}, nil
}

type ParquetStreamWriter struct {
	pw *writer.ParquetWriter
	fc io.Closer
}

func (w *ParquetStreamWriter) Write(rec Record) error {
	return w.pw.Write(rec)
}

func (w *ParquetStreamWriter) Close() error {
	if err := w.pw.WriteStop(); err != nil {
		w.fc.Close()
		return err
	}
	return w.fc.Close()
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
