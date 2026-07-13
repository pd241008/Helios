package helios

import org.apache.spark.sql.{DataFrame, Row, SparkSession}
import org.apache.spark.sql.types._
import org.apache.spark.sql.functions._
import org.apache.sedona.sql.utils.SedonaSQLRegistrator
import org.scalatest.BeforeAndAfterAll
import org.scalatest.flatspec.AnyFlatSpec
import org.scalatest.matchers.should.Matchers

class LSTMathTest extends AnyFlatSpec with Matchers with BeforeAndAfterAll {

  private var spark: SparkSession = _

  override def beforeAll(): Unit = {
    spark = SparkSession.builder()
      .appName("lst-math-test")
      .master("local[*]")
      .config("spark.sql.adaptive.enabled", "false")
      .config("spark.serializer", "org.apache.spark.serializer.JavaSerializer")
      .getOrCreate()
    spark.sparkContext.setLogLevel("WARN")
    SedonaSQLRegistrator.registerAll(spark)
  }

  override def afterAll(): Unit = {
    if (spark != null) spark.stop()
  }

  private val testCfg = PipelineConfig(
    ndviSoil             = 0.2,
    ndviVeg              = 0.5,
    emissivitySoilBand10 = 0.971,
    emissivityVegBand10  = 0.987,
    emissivitySoilBand11 = 0.977,
    emissivityVegBand11  = 0.989,
    swA0                 = -0.410,
    swA1                 = 1.000,
    swA2                 = 0.000,
    swA3                 = 0.000,
    swA4                 = 1.100,
    swA5                 = 0.000,
    swA6                 = 0.500,
    waterVapor           = 2.0,
  )

  private val pixelSchema = StructType(Seq(
    StructField("B4_Red",  DoubleType),
    StructField("B5_NIR",  DoubleType),
    StructField("B10_TIR", DoubleType),
    StructField("B11_TIR", DoubleType),
    StructField("lat",     DoubleType),
    StructField("lon",     DoubleType),
    StructField("tile_id", StringType),
  ))

  private val k1_10 = 774.8853
  private val k2_10 = 1321.0789
  private val k1_11 = 480.8883
  private val k2_11 = 1201.1442

  private def makePixelDF(pixels: Seq[Row]): DataFrame = {
    val s = spark
    import s.implicits._
    s.createDataFrame(s.sparkContext.parallelize(pixels), pixelSchema)
      .withColumn("ndvi", ($"B5_NIR" - $"B4_Red") / ($"B5_NIR" + $"B4_Red" + 1e-10))
      .withColumn("timestamp", lit(1709251200000L))
      .withColumn("lulc_class", lit("test"))
      .withColumn("zoning_category", lit("test"))
  }

  private def makeMetadata(sceneId: String): DataFrame = {
    val metaSchema = StructType(Seq(
      StructField("scene_id",            StringType),
      StructField("k1_constant_band_10", DoubleType),
      StructField("k2_constant_band_10", DoubleType),
      StructField("k1_constant_band_11", DoubleType),
      StructField("k2_constant_band_11", DoubleType),
    ))
    val s = spark
    import s.implicits._
    s.createDataFrame(
      s.sparkContext.parallelize(Seq(Row(sceneId, k1_10, k2_10, k1_11, k2_11))),
      metaSchema,
    )
  }

  behavior of "LSTMath.computeLST"

  it should "compute split-window LST when B11_TIR is present" in {
    // Physically plausible values: B4/B5 as surface reflectance, B10/B11 as
    // thermal radiance (W/m2/sr/um). B11 radiance is ~85% of B10 for realism.
    val pixels = makePixelDF(Seq(
      // Bare soil: B4=0.12, B5=0.16 (NDVI~0.14, Pv~0.04), L10=10.0, L11=8.5
      Row(0.12, 0.16, 10.0, 8.5, 12.90, 80.20, "LC08_L2SP_044034_20240301"),
      // Moderate veg: B4=0.08, B5=0.25 (NDVI~0.52, Pv~1.0 capped), L10=9.0, L11=7.65
      Row(0.08, 0.25, 9.0, 7.65, 13.05, 80.15, "LC08_L2SP_044034_20240301"),
      // Water: B4=0.03, B5=0.02 (NDVI~-0.2, Pv=0), L10=8.0, L11=6.8
      Row(0.03, 0.02, 8.0, 6.8, 13.10, 80.30, "LC08_L2SP_044034_20240301"),
    ))

    val meta = makeMetadata("LC08_L2SP_044034_20240301")

    val result = LSTMath.computeLST(pixels, meta, testCfg)
    result.cache()

    result.columns should contain ("lst")
    result.columns should contain ("bt10")
    result.columns should contain ("has_thermal_split")
    result.columns should contain ("pv")
    result.columns should contain ("eps10")
    result.columns should contain ("eps11")

    val rows = result.collect()
    rows.length shouldBe 3

    // All rows should have has_thermal_split = true (B11 was present)
    rows.foreach { row =>
      row.getBoolean(result.schema.fieldIndex("has_thermal_split")) shouldBe true
    }

    // Split-window LST must differ from the BT10 fallback (non-zero correction terms)
    rows.foreach { row =>
      val lst  = row.getDouble(result.schema.fieldIndex("lst"))
      val bt10 = row.getDouble(result.schema.fieldIndex("bt10"))
      withClue(s"Split-window LST ($lst) should differ from BT10 ($bt10)") {
        math.abs(lst - bt10) should be > 0.01
      }
    }

    // All LST values should be physically plausible for Earth surface
    // (output is in Kelvin; ~250-330 K is typical)
    rows.foreach { row =>
      val lst = row.getDouble(result.schema.fieldIndex("lst"))
      withClue(s"Split-window LST value $lst outside plausible range [250, 360] K") {
        lst should (be > 250.0 and be < 360.0)
      }
    }

    result.unpersist()
  }

  it should "fall back to BT10 when B11_TIR is absent" in {
    val pixels = makePixelDF(Seq(
      Row(0.12, 0.16, 10.0, 8.5, 12.90, 80.20, "NO_B11_SCENE"),
    )).drop("B11_TIR")

    val meta = makeMetadata("NO_B11_SCENE")

    val result = LSTMath.computeLST(pixels, meta, testCfg)
    result.cache()

    result.columns should contain ("lst")
    result.columns should contain ("bt10")
    result.columns should contain ("has_thermal_split")

    val row = result.collect().head
    val lst  = row.getDouble(result.schema.fieldIndex("lst"))
    val bt10 = row.getDouble(result.schema.fieldIndex("bt10"))

    // Without B11, lst equals bt10 (final fallback)
    lst shouldBe bt10 +- 0.001
    row.getBoolean(result.schema.fieldIndex("has_thermal_split")) shouldBe false

    result.unpersist()
  }

  it should "produce split-window and single-channel values within plausible delta" in {
    val pixels = makePixelDF(Seq(
      Row(0.12, 0.16, 10.0, 8.5, 12.90, 80.20, "LC08_L2SP_044034_20240301"),
    ))

    val meta = makeMetadata("LC08_L2SP_044034_20240301")

    // ST_B10 is the L2 atmospherically corrected single-channel baseline
    val withSTB10 = pixels.withColumn("ST_B10", lit(302.0))

    val result = LSTMath.computeLST(withSTB10, meta, testCfg)

    result.columns should contain ("lst")
    result.columns should contain ("ST_B10")

    val row = result.collect().head
    val lst = row.getDouble(result.schema.fieldIndex("lst"))
    val st  = row.getDouble(result.schema.fieldIndex("ST_B10"))

    // Both are estimating the same physical quantity; should be within 10 K
    math.abs(lst - st) should be < 10.0
  }
}
