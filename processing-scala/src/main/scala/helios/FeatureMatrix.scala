package helios

import org.apache.spark.sql.{DataFrame, SparkSession}
import org.apache.spark.sql.functions._

object FeatureMatrix {

  def assemble(
    df: DataFrame,
    cfg: PipelineConfig,
  ): DataFrame = {
    val baseCols = Seq(
      "tile_id", "lat", "lon", "year",
      "lulc_class_encoded", "zoning_category_encoded",
      "ndvi", "ndbi",
      "lst",
    )

    val extraCols = df.columns.toSet -- baseCols.toSet
    val wanted = baseCols ++ extraCols.filter(c =>
      c.startsWith("B") || c.startsWith("ST_") || c == "pv" || c == "eps10" || c == "eps11" || c == "bt10" || c == "has_thermal_split"
    )

    val selected = df.select(wanted.map(col): _*)

    val roundCols = selected.schema.fields
      .filter(f => f.dataType.typeName == "double" || f.dataType.typeName == "float")
      .map(_.name)

    var rounded = selected
    for (rc <- roundCols) {
      rounded = rounded.withColumn(rc, round(col(rc), 4))
    }

    val splitFlag = when(
      col("year").between(cfg.trainYearStart, cfg.trainYearEnd), lit("train")
    ).when(
      col("year").between(cfg.testYearStart, cfg.testYearEnd), lit("test")
    ).otherwise(lit("ignore"))

    rounded
      .withColumn("split", splitFlag)
      .filter(col("split") =!= "ignore")
      .na.drop(List("lst", "lat", "lon"))
  }

  def write(df: DataFrame, outputDir: String): Unit = {
    df.write
      .mode("overwrite")
      .partitionBy("year", "split")
      .option("compression", "zstd")
      .parquet(outputDir)

    println(s"  Dense matrix: ${df.count()} rows × ${df.columns.length} cols")
    println(s"  Partitioned by year/split → $outputDir")
  }
}
