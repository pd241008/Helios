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
)

object PipelineConfig {
  def fromArgs(args: Array[String]): PipelineConfig = {
    val m = args.sliding(2, 2).collect {
      case Array(k, v) if k.startsWith("--") => k.drop(2) -> v
    }.toMap

    def d(k: String, fallback: Double) = m.get(k).map(_.toDouble).getOrElse(fallback)
    def i(k: String, fallback: Int)    = m.get(k).map(_.toInt).getOrElse(fallback)
    def s(k: String, fallback: String) = m.getOrElse(k, fallback)

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
    )
  }
}
