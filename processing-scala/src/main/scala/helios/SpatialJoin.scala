package helios

import org.apache.spark.sql.{DataFrame, SparkSession}
import org.apache.spark.sql.functions._
import org.apache.spark.storage.StorageLevel
import org.apache.spark.storage.StorageLevel

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

    // LEFT JOIN: assign a zone category to every pixel. Pixels outside
    // all zones get null for the category column. This gives us the
    // "before zone-filter" count (count-2).
    val joinedAll = pixels.sparkSession.sql(
      s"""
      SELECT /*+ BROADCAST(z) */ p.*, z.$categoryCol
      FROM pixels p LEFT JOIN zones z
      ON ST_Contains(z.geometry, ST_Point(p.lon, p.lat))
      """
    )
    val totalJoined = joinedAll.count()
    println(s"  [count-2] Spatial join (LEFT, all pixels, before zone filter): $totalJoined rows")

    // INNER filter: keep only pixels that fell inside a zone polygon.
    // This is the count-3 metric. The difference (count-2 − count-3)
    // is "pixels outside all zones" — expected to be large because the
    // parser reads the full 185 km × 185 km Landsat scene, while zones
    // cover only a small fraction of it.
    val joined = joinedAll.filter(col(categoryCol).isNotNull)
    val numInsideZones = joined.count()
    val outsideAllZones = totalJoined - numInsideZones
    println(s"  [count-3] Pixels inside any zone (after zone filter): $numInsideZones rows")
    println(s"  Pixels outside all zones (count-2 − count-3): $outsideAllZones rows")
    if (totalJoined > 0) {
      println(s"  Zone coverage: ${"%.2f".format(numInsideZones.toDouble / totalJoined * 100)}% of pivoted pixels")
    }

    println("\n═══ Spatial Join Physical Plan ═══")
    joined.explain(true)
    println()
    joined
  }

  def runPivotAndJoin(
    spark: SparkSession,
    inputDir: String,
    zoningPath: String,
    categoryCol: String,
    sampleRate: Double = 1.0,
  ): DataFrame = {
    // ── STAGE COUNT 0: raw parquet load ──────────────────────────
    // Reads ALL parquet files under landsat/. Each file is one Landsat
    // scene (~185 km × 185 km). The parser reads the full scene, NOT
    // just the analysis bbox; the spatial join later clips to zones.
    val raw = spark.read.parquet(s"$inputDir/landsat/*.parquet")

    // sampleRate: dev-only safety valve. Default 1.0 = full resolution.
    // Sampling at the aggregation stage destroys spatial analysis fidelity
    // and must NEVER be used to produce a result presented as validating
    // the pipeline. Sampling belongs at the ML training stage only.
    // If full-resolution OOMs on this machine, document the memory
    // requirement rather than decimating.
    val sampled = if (sampleRate < 1.0 && sampleRate > 0.0) {
      println(s"  ╔══════════════════════════════════════════════════════════════╗")
      println(s"  ║  WARNING: --sample-rate $sampleRate IS ACTIVE.                   ║")
      println(s"  ║  Results are APPROXIMATE and do NOT validate the pipeline.  ║")
      println(s"  ║  Full resolution (sample-rate 1.0) is required for any      ║")
      println(s"  ║  spatial analysis. This flag exists only for dev machines    ║")
      println(s"  ║  with ≤8 GB RAM where the pivot hash table exceeds heap.    ║")
      println(s"  ╚══════════════════════════════════════════════════════════════╝")
      raw.sample(false, sampleRate, seed = 42)
    } else {
      raw
    }

    val rawCount = sampled.count()
    println(s"  [count-0] Long-format records loaded: $rawCount")
    sampled.printSchema()

    // ── STAGE COUNT 1: pivot ─────────────────────────────────────
    // Pivot collapses per-band rows into one wide row per unique
    // (tile_id, lat, lon, timestamp, lulc_class). The parser reads
    // 4 bands per pixel for PC L2 data (B4, B5, B6, ST_B10), so
    // at full resolution ~25% of raw records survive as pivoted rows
    // (after QA and nodata filtering reduce some bands per pixel).
    val pivoted = pivotBands(sampled)
    val numPixels = pivoted.count()
    println(s"  [count-1] Pivoted wide pixels: $numPixels")

    val zones = loadLULC(spark, zoningPath)
    val zoneCount = zones.count()
    println(s"  LULC zones loaded: $zoneCount")
    zones.printSchema()

    // ── STAGE COUNT 2 & 3: spatial join + zone filter ────────────
    // The parser reads the FULL 185 km × 185 km Landsat scene, but the
    // zone polygons cover only a fraction of the scene area. The inner
    // spatial join (ST_Contains) clips to zones — this is the dominant
    // source of row reduction. Three separate counts are printed:
    //   count-2: after LEFT JOIN (all pivoted pixels, zone assigned or null)
    //   count-3: after filtering to pixels inside a zone (INNER semantics)
    //   "outside all zones" = count-2 − count-3
    val joined = spatialJoin(pivoted, zones, categoryCol)
    // Cache the join result — it will be used 3 times downstream
    // (zone distribution count, LST computation, and diagnostics).
    // MEMORY_AND_DISK_SER serializes to reduce memory footprint.
    joined.persist(StorageLevel.MEMORY_AND_DISK_SER)
    val numJoined = joined.count()
    println(s"  Spatial join result (inside zones): $numJoined rows")
    println(s"  Spatial join result cached (MEMORY_AND_DISK_SER)")

    joined
  }
}
