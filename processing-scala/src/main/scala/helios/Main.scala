package helios

import org.apache.spark.sql.SparkSession
import org.apache.spark.sql.functions._

/**
 * Entry point for the Helios Spark processing pipeline.
 *
 * Reads raw Parquet shards produced by the Go ingestion layer,
 * performs spatial joins, applies target encoding on high-cardinality
 * categorical columns (LULC classes, zoning), and writes a dense,
 * ML-ready Parquet matrix.
 *
 * Usage (via sbt):
 *   sbt "runMain helios.Main --input /staging/raw --output /staging/dense"
 */
object Main {

  def main(args: Array[String]): Unit = {
    // ── Parse CLI args ───────────────────────────────────────────
    val argMap = parseArgs(args)
    val inputDir  = argMap.getOrElse("input",  "./staging/raw")
    val outputDir = argMap.getOrElse("output", "./staging/dense")

    // ── Spark session ────────────────────────────────────────────
    val spark = SparkSession.builder()
      .appName("helios-processing")
      .master("local[*]")  // Override in cluster submission
      .config("spark.sql.adaptive.enabled", "true")
      .config("spark.sql.parquet.compression.codec", "zstd")
      .config("spark.serializer", "org.apache.spark.serializer.KryoSerializer")
      .getOrCreate()

    spark.sparkContext.setLogLevel("WARN")

    try {
      println(s"═══ Helios Processing Pipeline ═══")
      println(s"  Input:  $inputDir")
      println(s"  Output: $outputDir")

      // ── 1. Read raw ingested Parquet ─────────────────────────
      val rawDF = spark.read
        .parquet(s"$inputDir/landsat", s"$inputDir/osm")
        .na.drop()  // Drop rows with null values from incomplete fetches

      println(s"  Raw records: ${rawDF.count()}")
      rawDF.printSchema()

      // ── 2. Spatial join (band pivot + OSM density merge) ────
      val pivoted = SpatialJoin.pivotBands(rawDF)

      // ── 3. Target encoding on high-cardinality LULC classes ─
      //    This encodes the 18-fold LULC categories into
      //    smoothed mean-target values, preventing overfitting
      //    on rare classes.
      val encoded = TargetEncoder.encode(
        df          = pivoted,
        targetCol   = "B10_TIR",       // Thermal band as proxy for LST
        catCols     = Seq("lulc_class"),
        smoothing   = 10.0
      )

      // ── 4. Write dense ML-ready matrix ──────────────────────
      encoded.write
        .mode("overwrite")
        .option("compression", "zstd")
        .parquet(outputDir)

      println(s"  Dense matrix: ${encoded.count()} rows × ${encoded.columns.length} cols")
      println(s"  Written to: $outputDir")
      println(s"═══ Processing complete ═══")

    } finally {
      spark.stop()
    }
  }

  /** Simple --key value argument parser. */
  private def parseArgs(args: Array[String]): Map[String, String] = {
    args.sliding(2, 2).collect {
      case Array(key, value) if key.startsWith("--") =>
        key.stripPrefix("--") -> value
    }.toMap
  }
}
