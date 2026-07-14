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

    val hasB10   = withMeta.columns.contains("B10_TIR")
    val hasB11   = withMeta.columns.contains("B11_TIR")
    val hasSTB10 = withMeta.columns.contains("ST_B10")

    // BT10 can only be computed from raw B10_TIR. If absent (PC L2 source),
    // bt10 is a null placeholder — only ST_B10 or split-window is available.
    val b10  = if (hasB10) col("B10_TIR") else lit(null).cast("double")
    val bt10 = if (hasB10) k2_10 / ln(k1_10 / b10 + lit(1.0))
               else lit(null).cast("double")

    val lst = if (hasB11 && hasB10) {
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
    } else if (hasB10) {
      bt10
    } else {
      lit(null).cast("double")
    }

    val (bt11Col, dBTCol) = if (hasB11 && hasB10) {
      val b11  = col("B11_TIR")
      val bt11 = k2_11 / ln(k1_11 / b11 + lit(1.0))
      (bt11, bt10 - bt11)
    } else {
      (lit(null).cast("double"), lit(null).cast("double"))
    }

    withMeta
      .withColumn("pv", pv)
      .withColumn("eps10", eps10)
      .withColumn("eps11", eps11)
      .withColumn("bt10", bt10)
      .withColumn("bt11", bt11Col)
      .withColumn("bt10_minus_bt11", dBTCol)
      .withColumn("lst", lst)
      .withColumn("has_thermal_split", lit(hasB11 && hasB10))
  }
}
