package helios

case class PipelineConfig(
  inputDir:              String = "./staging/raw",
  outputDir:             String = "./staging/dense",
  zoningPath:            String = "./staging/raw/zoning.geojson",
  metadataDir:           String = "",
  lulcCategoryCol:       String = "zoning_category",
  ndviSoil:              Double = 0.2,
  ndviVeg:               Double = 0.5,
  emissivitySoilBand10:  Double = 0.966,
  emissivityVegBand10:   Double = 0.986,
  emissivitySoilBand11:  Double = 0.973,
  emissivityVegBand11:   Double = 0.989,
  swA0:                  Double = -0.410,
  swA1:                  Double = 1.000,
  swA2:                  Double = 0.000,
  swA3:                  Double = 0.000,
  swA4:                  Double = 1.100,
  swA5:                  Double = 0.000,
  swA6:                  Double = 0.500,
  waterVapor:            Double = 2.0,
  targetSmoothing:       Double = 10.0,
  trainYearStart:        Int = 2024,
  trainYearEnd:          Int = 2031,
  testYearStart:         Int = 2032,
  testYearEnd:           Int = 2033,
  // sampleRate: DEV-ONLY safety valve. Must default to 1.0 (full resolution).
  // Sampling destroys spatial analysis fidelity — every pixel must reach the
  // feature matrix for the urban-heat zoning analysis to be statistically
  // valid. Sampling belongs at the ML training stage (cross-validation folds),
  // NOT in the aggregation pipeline. Use only on constrained dev machines
  // (≤8 GB RAM) where the pivot hash table exceeds available heap. Any result
  // produced with sampleRate < 1.0 is explicitly NOT a pipeline validation.
  sampleRate:            Double = 1.0,
  // allowDegenerateSplit: opt-in bypass for pilot/smoke-test runs where
  // train and test year ranges intentionally overlap (e.g. single-scene
  // validation). Must be an explicit CLI flag — never the silent default.
  allowDegenerateSplit:  Boolean = false,
) {

  /** Validate that train/test year ranges do not overlap.
    *
    * Spark's .when() chain in FeatureMatrix evaluates in order and stops at
    * first match.  If the train range [trainYearStart, trainYearEnd] overlaps
    * the test range [testYearStart, testYearEnd], every matching year silently
    * gets "train" and the test branch is unreachable — producing a dense matrix
    * with zero test rows and no error.
    *
    * Call this before any Spark job runs.  Throws IllegalArgumentException
    * if the ranges overlap and allowDegenerateSplit is not set.
    */
  def validateYearRanges(): Unit = {
    val rangesOverlap = trainYearStart <= testYearEnd && testYearStart <= trainYearEnd
    if (rangesOverlap && !allowDegenerateSplit) {
      val overlapStart = math.max(trainYearStart, testYearStart)
      val overlapEnd   = math.min(trainYearEnd, testYearEnd)
      val years = if (overlapStart == overlapEnd) s"year $overlapStart"
                  else s"years $overlapStart–$overlapEnd"
      throw new IllegalArgumentException(
        s"""Train/test year ranges overlap on $years.
           |
           |  train range: [${trainYearStart}, ${trainYearEnd}]
           |  test  range: [${testYearStart}, ${testYearEnd}]
           |
           |Spark's chained .when() assigns split in priority order (train
           |first, then test).  Overlapping years silently get "train",
           |producing a dense matrix with zero test rows.
           |
           |Fix: use non-overlapping year ranges, or pass
           |  --allow-degenerate-split true
           |to explicitly opt in for pilot/smoke-test runs.""".stripMargin
      )
    }
  }
}

object PipelineConfig {
  def fromArgs(args: Array[String]): PipelineConfig = {
    val m = args.sliding(2, 2).collect {
      case Array(k, v) if k.startsWith("--") => k.drop(2) -> v
    }.toMap

    def d(k: String, fallback: Double) = m.get(k).map(_.toDouble).getOrElse(fallback)
    def i(k: String, fallback: Int)    = m.get(k).map(_.toInt).getOrElse(fallback)
    def s(k: String, fallback: String) = m.getOrElse(k, fallback)
    def b(k: String, fallback: Boolean) = m.get(k).map(_.toBoolean).getOrElse(fallback)

    PipelineConfig(
      inputDir              = s("input",              "./staging/raw"),
      outputDir             = s("output",             "./staging/dense"),
      zoningPath            = s("zoning-path",        "./staging/raw/zoning.geojson"),
      metadataDir           = s("metadata-dir",       ""),
      lulcCategoryCol       = s("lulc-category-col",  "zoning_category"),
      ndviSoil              = d("ndvi-soil",          0.2),
      ndviVeg               = d("ndvi-veg",           0.5),
      emissivitySoilBand10  = d("emis-soil-10",       0.966),
      emissivityVegBand10   = d("emis-veg-10",        0.986),
      emissivitySoilBand11  = d("emis-soil-11",       0.973),
      emissivityVegBand11   = d("emis-veg-11",        0.989),
      swA0                  = d("sw-a0",              -0.410),
      swA1                  = d("sw-a1",              1.000),
      swA2                  = d("sw-a2",              0.000),
      swA3                  = d("sw-a3",              0.000),
      swA4                  = d("sw-a4",              1.100),
      swA5                  = d("sw-a5",              0.000),
      swA6                  = d("sw-a6",              0.500),
      waterVapor            = d("water-vapor",        2.0),
      targetSmoothing       = d("target-smoothing",   10.0),
      trainYearStart        = i("train-year-start",   2024),
      trainYearEnd          = i("train-year-end",     2031),
      testYearStart         = i("test-year-start",    2032),
      testYearEnd           = i("test-year-end",      2033),
      sampleRate            = d("sample-rate",        1.0),
      allowDegenerateSplit  = b("allow-degenerate-split", false),
    )
  }
}
