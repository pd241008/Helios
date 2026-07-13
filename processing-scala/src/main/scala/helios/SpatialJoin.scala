package helios

import org.apache.spark.sql.{DataFrame, SparkSession}
import org.apache.spark.sql.functions._

object SpatialJoin {

  def pivotBands(df: DataFrame): DataFrame = {
    val pivoted = df
      .groupBy("tile_id", "lat", "lon", "timestamp", "lulc_class")
      .pivot("band")
      .agg(first("value"))

    val ndvi = (col("B5_NIR") - col("B4_Red")) / (col("B5_NIR") + col("B4_Red") + 1e-10)
    val ndbi = (col("B6_SWIR1") - col("B5_NIR")) / (col("B6_SWIR1") + col("B5_NIR") + 1e-10)

    pivoted
      .withColumn("year", year(col("timestamp")))
      .withColumn("ndvi", ndvi)
      .withColumn("ndbi", ndbi)
  }

  def loadLULC(spark: SparkSession, zoningPath: String): DataFrame = {
    val raw = spark.read
      .option("multiline", "true")
      .json(zoningPath)

    raw
      .select(explode(col("features")).as("feature"))
      .select(
        col("feature.properties.zoning_category").as("zoning_category"),
        to_json(col("feature.geometry")).as("geom_json")
      )
      .select(
        col("zoning_category"),
        expr("ST_GeomFromGeoJSON(geom_json)").as("geometry")
      )
  }

  def spatialJoin(
    pixels: DataFrame,
    zones: DataFrame,
    categoryCol: String,
  ): DataFrame = {
    pixels.createOrReplaceTempView("pixels")
    zones.createOrReplaceTempView("zones")

    val joined = pixels.sparkSession.sql(
      s"""
      SELECT /*+ BROADCAST(z) */ p.*, z.$categoryCol
      FROM pixels p, zones z
      WHERE ST_Contains(z.geometry, ST_Point(p.lon, p.lat))
      """
    )
    joined
  }

  def runPivotAndJoin(
    spark: SparkSession,
    inputDir: String,
    zoningPath: String,
    categoryCol: String,
  ): DataFrame = {
    val raw = spark.read.parquet(s"$inputDir/landsat/*.parquet")
    println(s"  Long-format records loaded: ${raw.count()}")
    raw.printSchema()

    val pivoted = pivotBands(raw)
    val numPixels = pivoted.count()
    println(s"  Pivoted wide pixels: $numPixels")

    val zones = loadLULC(spark, zoningPath)
    val zoneCount = zones.count()
    println(s"  LULC zones loaded: $zoneCount")
    zones.printSchema()

    val joined = spatialJoin(pivoted, zones, categoryCol)
    val numJoined = joined.count()
    println(s"  Spatial join result: $numJoined rows")
    joined
  }
}
