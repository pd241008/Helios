package helios

import org.apache.spark.sql.{DataFrame, SparkSession}
import org.apache.spark.sql.functions._
import org.apache.spark.storage.StorageLevel
import org.apache.spark.storage.StorageLevel

object SpatialJoin {

  // Chennai AOI bounding box — same coordinates used throughout the pipeline
  // (Go ingestion --bbox, Makefile, Python analysis scripts).
  // All zone polygons lie within this box, so any pixel outside it is
  // guaranteed to be discarded by the spatial join's INNER filter.
  val CHENNAI_BBOX_LON_MIN = 79.9469
  val CHENNAI_BBOX_LON_MAX = 80.3450
  val CHENNAI_BBOX_LAT_MIN = 12.8000
  val CHENNAI_BBOX_LAT_MAX = 13.2300

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
    // ── Parquet load ─────────────────────────────────────────────
    // Reads ALL parquet files under landsat/. Each file is one
    // Landsat scene (~185 km × 185 km). The parser reads the full
    // scene, NOT just the analysis bbox; the bbox filter below
    // clips to the Chennai AOI before the pivot.
    val raw = spark.read.parquet(s"$inputDir/landsat/*.parquet")

    // sampleRate: dev-only safety valve. Default 1.0 = full resolution.
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

    // ── AOI bounding-box pre-filter ──────────────────────────────
    // The Landsat scene footprint is 185 km × 185 km; the Chennai
    // analysis area is a small fraction of that. Filtering to the
    // AOI bbox BEFORE the pivot shrinks the groupBy hash table from
    // ~1.06B rows to ~250-270M (extrapolating ~25% bbox coverage
    // per scene × 7 scenes). This eliminates the OOM at the pivot
    // and the subsequent spatial join because:
    //   • All zone polygons lie inside this bbox, so no pixel
    //     outside the bbox is ever needed downstream (LST math,
    //     target encoding's global mean, feature matrix all operate
    //     on zone-matched pixels only).
    //   • The spatial join's INNER filter would discard them anyway.
    val inBbox = col("lon").between(CHENNAI_BBOX_LON_MIN, CHENNAI_BBOX_LON_MAX) &&
                 col("lat").between(CHENNAI_BBOX_LAT_MIN, CHENNAI_BBOX_LAT_MAX)
    val filtered = sampled.filter(inBbox)

    // ── STAGE COUNT 0: raw parquet load ──────────────────────────
    // NOTE: We deliberately skip a separate sampled.count() here
    // because reading 19 GB of parquet just to count rows exhausts
    // the JVM memory pool and causes EOFException on the next read.
    // The pivot below will read the parquet with the bbox filter
    // applied inline (filter pushdown). We print a row-count
    // estimate from the pivoted result instead.
    println(s"  [count-0] Skipping explicit raw count (bbox filter applied inline)")
    sampled.printSchema()

    // ── STAGE COUNT 1: pivot ─────────────────────────────────────
    // Pivot collapses per-band rows into one wide row per unique
    // (tile_id, lat, lon, timestamp, lulc_class). The parser reads
    // 4 bands per pixel for PC L2 data (B4, B5, B6, ST_B10), so
    // at full resolution ~25% of raw records survive as pivoted rows
    // (after QA and nodata filtering reduce some bands per pixel).
    val pivoted = pivotBands(filtered)
    val numPixels = pivoted.count()
    println(s"  [count-1] Pivoted wide pixels (after bbox filter): $numPixels")

    val zones = loadLULC(spark, zoningPath)
    val zoneCount = zones.count()
    println(s"  LULC zones loaded: $zoneCount")
    zones.printSchema()

    // ── STAGE COUNT 2 & 3: spatial join + zone filter ────────────
    // The AOI bbox pre-filter has already clipped pixels to the
    // Chennai analysis area. The spatial join (ST_Contains) further
    // restricts to pixels inside zone polygons — the final reduction.
    // Three separate counts are printed:
    //   count-2: after LEFT JOIN (all bbox-filtered pixels, zone assigned or null)
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
