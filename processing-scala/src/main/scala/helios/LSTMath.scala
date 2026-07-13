package helios

import org.apache.spark.sql.{DataFrame, SparkSession}
import org.apache.spark.sql.functions._

object LSTMath {

  def loadMetadata(spark: SparkSession, metadir: String): DataFrame = {
    val dir = new java.io.File(metadir)
    val metaFiles = dir.listFiles()
      .filter(_.isDirectory)
      .flatMap { d =>
        val f = new java.io.File(d, "scene_metadata.json")
        if (f.exists()) Some(f.getAbsolutePath) else None
      }
    if (metaFiles.isEmpty) {
      println(s"  WARNING: no scene_metadata.json found under $metadir")
      spark.emptyDataFrame
    } else {
      println(s"  Metadata files: ${metaFiles.length} found")
      spark.read.option("multiline", "true").json(metaFiles: _*)
    }
  }

  def computeLST(
    pixels: DataFrame,
    meta: DataFrame,
    cfg: PipelineConfig,
  ): DataFrame = {
    val metaClean = meta
      .withColumnRenamed("scene_id", "mscene_id")
      .select(
        col("mscene_id"),
        col("k1_constant_band_10"),
        col("k2_constant_band_10"),
        col("k1_constant_band_11"),
        col("k2_constant_band_11"),
      )

    val withMeta = pixels
      .join(metaClean, col("tile_id") === col("mscene_id"), "left")
      .drop("mscene_id")

    val ndvi  = col("ndvi")
    val b10   = col("B10_TIR")
    val k1_10 = col("k1_constant_band_10")
    val k2_10 = col("k2_constant_band_10")
    val k1_11 = col("k1_constant_band_11")
    val k2_11 = col("k2_constant_band_11")

    val pvRaw = ((ndvi - cfg.ndviSoil) / (cfg.ndviVeg - cfg.ndviSoil))
    val pv = when(ndvi.isNull || ndvi.isNaN, 0.0)
      .when(ndvi < cfg.ndviSoil, 0.0)
      .when(ndvi > cfg.ndviVeg, 1.0)
      .otherwise(pvRaw * pvRaw)

    val eps10 = lit(cfg.emissivitySoilBand10) * (lit(1.0) - pv) + lit(cfg.emissivityVegBand10) * pv
    val eps11 = lit(cfg.emissivitySoilBand11) * (lit(1.0) - pv) + lit(cfg.emissivityVegBand11) * pv

    val bt10 = k2_10 / ln(k1_10 / b10 + lit(1.0))

    val hasB11   = withMeta.columns.contains("B11_TIR")
    val hasSTB10 = withMeta.columns.contains("ST_B10")

    // The B11 fallback path is intentionally kept as a resilience mechanism
    // for real-world tiles where B11 ingestion failed or the band was
    // unavailable from the STAC source. When B11_TIR is absent, LST
    // degrades to single-channel BT10 (or ST_B10 if available) rather than
    // failing the pipeline outright.
    val lst = if (hasB11) {
      val b11   = col("B11_TIR")
      val bt11  = k2_11 / ln(k1_11 / b11 + lit(1.0))
      val dBT   = bt10 - bt11
      val meanE = (eps10 + eps11) / lit(2.0)
      val dEps  = eps10 - eps11

      bt10 +
        lit(cfg.swA0) +
        lit(cfg.swA1) * dBT +
        lit(cfg.swA2) * (dBT * dBT) +
        (lit(cfg.swA3) + lit(cfg.swA4) * lit(cfg.waterVapor)) * (lit(1.0) - meanE) +
        (lit(cfg.swA5) + lit(cfg.swA6) * lit(cfg.waterVapor)) * dEps
    } else if (hasSTB10) {
      col("ST_B10")
    } else {
      bt10
    }

    val lstCol = lst

    withMeta
      .withColumn("pv", pv)
      .withColumn("eps10", eps10)
      .withColumn("eps11", eps11)
      .withColumn("bt10", bt10)
      .withColumn("lst", lstCol)
      .withColumn("has_thermal_split", lit(hasB11))
  }
}
