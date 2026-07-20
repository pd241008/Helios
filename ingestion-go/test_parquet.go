package main

import (
"fmt"
"os"

"github.com/apache/arrow-go/v18/parquet"
"github.com/apache/arrow-go/v18/parquet/file"
"github.com/apache/arrow-go/v18/parquet/schema"
)

func main() {
sc, err := schema.NewGroupNode("schema", parquet.Repetitions.Required, schema.FieldList{
schema.NewByteArrayNode("tile_id", parquet.Repetitions.Required, -1),
}, -1)
if err != nil {
fmt.Println("Error:", err)
return
}
fmt.Println(sc.Name())
}
