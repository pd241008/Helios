package helios

import org.scalatest.flatspec.AnyFlatSpec
import org.scalatest.matchers.should.Matchers

class ConfigTest extends AnyFlatSpec with Matchers {

  behavior of "PipelineConfig.validateYearRanges"

  it should "pass when train and test ranges are non-overlapping (default config)" in {
    val cfg = PipelineConfig()
    // Default: train 2024–2031, test 2032–2033 — no overlap
    noException should be thrownBy cfg.validateYearRanges()
  }

  it should "fail when train and test ranges overlap (degenerate single-year)" in {
    // The exact bug that was discovered: all four values equal 2023
    val cfg = PipelineConfig(
      trainYearStart = 2023,
      trainYearEnd   = 2023,
      testYearStart  = 2023,
      testYearEnd    = 2023,
    )
    val ex = the[IllegalArgumentException] thrownBy cfg.validateYearRanges()
    ex.getMessage should include ("overlap")
    ex.getMessage should include ("year 2023")
  }

  it should "fail when ranges share a boundary year" in {
    // Train ends where test starts — they share one year
    val cfg = PipelineConfig(
      trainYearStart = 2020,
      trainYearEnd   = 2023,
      testYearStart  = 2023,
      testYearEnd    = 2025,
    )
    val ex = the[IllegalArgumentException] thrownBy cfg.validateYearRanges()
    ex.getMessage should include ("overlap")
    ex.getMessage should include ("year 2023")
  }

  it should "fail when test range is entirely inside train range" in {
    val cfg = PipelineConfig(
      trainYearStart = 2020,
      trainYearEnd   = 2030,
      testYearStart  = 2025,
      testYearEnd    = 2028,
    )
    val ex = the[IllegalArgumentException] thrownBy cfg.validateYearRanges()
    ex.getMessage should include ("overlap")
    ex.getMessage should include ("years 2025–2028")
  }

  it should "fail when train range is entirely inside test range" in {
    val cfg = PipelineConfig(
      trainYearStart = 2025,
      trainYearEnd   = 2028,
      testYearStart  = 2020,
      testYearEnd    = 2030,
    )
    val ex = the[IllegalArgumentException] thrownBy cfg.validateYearRanges()
    ex.getMessage should include ("overlap")
    ex.getMessage should include ("years 2025–2028")
  }

  it should "pass when ranges are adjacent but not overlapping" in {
    val cfg = PipelineConfig(
      trainYearStart = 2020,
      trainYearEnd   = 2024,
      testYearStart  = 2025,
      testYearEnd    = 2029,
    )
    noException should be thrownBy cfg.validateYearRanges()
  }

  it should "pass when ranges are disjoint" in {
    val cfg = PipelineConfig(
      trainYearStart = 2010,
      trainYearEnd   = 2015,
      testYearStart  = 2020,
      testYearEnd    = 2025,
    )
    noException should be thrownBy cfg.validateYearRanges()
  }

  it should "allow overlap when allowDegenerateSplit is true" in {
    val cfg = PipelineConfig(
      trainYearStart       = 2023,
      trainYearEnd         = 2023,
      testYearStart        = 2023,
      testYearEnd          = 2023,
      allowDegenerateSplit = true,
    )
    noException should be thrownBy cfg.validateYearRanges()
  }

  it should "allow overlap with flag even for partial range overlap" in {
    val cfg = PipelineConfig(
      trainYearStart       = 2020,
      trainYearEnd         = 2025,
      testYearStart        = 2023,
      testYearEnd          = 2028,
      allowDegenerateSplit = true,
    )
    noException should be thrownBy cfg.validateYearRanges()
  }

  it should "include actionable guidance in the error message" in {
    val cfg = PipelineConfig(
      trainYearStart = 2023,
      trainYearEnd   = 2023,
      testYearStart  = 2023,
      testYearEnd    = 2023,
    )
    val ex = the[IllegalArgumentException] thrownBy cfg.validateYearRanges()
    ex.getMessage should include ("--allow-degenerate-split")
    ex.getMessage should include ("train range")
    ex.getMessage should include ("test  range")
  }

  behavior of "PipelineConfig.fromArgs"

  it should "parse --allow-degenerate-split true" in {
    val cfg = PipelineConfig.fromArgs(Array(
      "--train-year-start", "2023",
      "--train-year-end", "2023",
      "--test-year-start", "2023",
      "--test-year-end", "2023",
      "--allow-degenerate-split", "true",
    ))
    cfg.allowDegenerateSplit shouldBe true
    cfg.trainYearStart shouldBe 2023
    // Should not throw because flag is set
    noException should be thrownBy cfg.validateYearRanges()
  }

  it should "default allowDegenerateSplit to false" in {
    val cfg = PipelineConfig.fromArgs(Array(
      "--train-year-start", "2023",
      "--train-year-end", "2023",
      "--test-year-start", "2023",
      "--test-year-end", "2023",
    ))
    cfg.allowDegenerateSplit shouldBe false
    val ex = the[IllegalArgumentException] thrownBy cfg.validateYearRanges()
    ex.getMessage should include ("overlap")
  }

  it should "parse default non-overlapping years" in {
    val cfg = PipelineConfig.fromArgs(Array())
    cfg.trainYearStart shouldBe 2024
    cfg.trainYearEnd shouldBe 2031
    cfg.testYearStart shouldBe 2032
    cfg.testYearEnd shouldBe 2033
    noException should be thrownBy cfg.validateYearRanges()
  }
}
