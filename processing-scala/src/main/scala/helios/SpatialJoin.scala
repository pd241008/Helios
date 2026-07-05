package helios

import org.apache.spark.sql.{DataFrame, SparkSession}
import org.apache.spark.sql.functions._

/**
 * Spatial join and band-pivoting operations.
 *
 * Takes raw per-pixel/per-band records and pivots them into a wide
 * format where each spectral band becomes its own column, keyed by
 * (tile_id, lat, lon, timestamp).
 *
 * For production spatial joins (e.g., point-in-polygon with zoning
 * boundaries), integrate Apache Sedona's ST_Contains / ST_Within.
 */
object SpatialJoin {

  /**
   * Pivots the long-format band records into a wide matrix.
   *
   * Input schema:
   *   tile_id | lat | lon | band | value | timestamp | lulc_class
   *
   * Output schema:
   *   tile_id | lat | lon | timestamp | lulc_class
   *   | B2_Blue | B3_Green | B4_Red | B5_NIR | B6_SWIR1 | B10_TIR
   *   | osm_density
   */
  def pivotBands(df: DataFrame): DataFrame = {
    // Group by the spatial key and pivot bands into columns.
    val pivoted = df
      .groupBy("tile_id", "lat", "lon", "timestamp", "lulc_class")
      .pivot("band")
      .agg(first("value"))

    // Derive engineered features.
    val withFeatures = pivoted
      .withColumn("ndvi",
        when(col("B5_NIR") + col("B4_Red") =!= 0,
          (col("B5_NIR") - col("B4_Red")) / (col("B5_NIR") + col("B4_Red"))
        ).otherwise(0.0)
      )
      .withColumn("ndbi",
        when(col("B6_SWIR1") + col("B5_NIR") =!= 0,
          (col("B6_SWIR1") - col("B5_NIR")) / (col("B6_SWIR1") + col("B5_NIR"))
        ).otherwise(0.0)
      )

    withFeatures
  }

  /**
   * Performs a spatial join between pixel observations and polygon
   * boundaries (e.g., zoning maps, administrative regions).
   *
   * TODO(production): Use Sedona for real geometry operations:
   *   SedonaSQLRegistrator.registerAll(spark)
   *   spark.sql("""
   *     SELECT p.*, z.zone_type
   *     FROM pixels p, zones z
   *     WHERE ST_Contains(z.geometry, ST_Point(p.lon, p.lat))
   *   """)
   */
  def joinWithZones(pixels: DataFrame, zones: DataFrame): DataFrame = {
    // Placeholder: cross-join with filter for bbox containment.
    // Replace with proper spatial index in production.
    pixels
      .join(zones, Seq("tile_id"), "left")
  }
}
