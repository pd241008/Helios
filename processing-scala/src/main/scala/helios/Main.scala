package helios

import org.apache.spark.sql.SparkSession
import org.apache.sedona.sql.utils.SedonaSQLRegistrator

object Main {

  def main(args: Array[String]): Unit = {
    val cfg = PipelineConfig.fromArgs(args)
    val metaDir = if (cfg.metadataDir.isEmpty) s"${cfg.inputDir}/landsat" else cfg.metadataDir

    println(s"═══ Helios Processing Pipeline ═══")
    println(s"  Input:   ${cfg.inputDir}")
    println(s"  Output:  ${cfg.outputDir}")
    println(s"  Zoning:  ${cfg.zoningPath}")
    println(s"  Years:   train=${cfg.trainYearStart}-${cfg.trainYearEnd}  test=${cfg.testYearStart}-${cfg.testYearEnd}")

    val spark = SparkSession.builder()
      .appName("helios-processing")
      .master("local[*]")
      .config("spark.sql.adaptive.enabled", "true")
      .config("spark.sql.parquet.compression.codec", "zstd")
      .config("spark.serializer", "org.apache.spark.serializer.JavaSerializer")
      .getOrCreate()

    spark.sparkContext.setLogLevel("WARN")

    SedonaSQLRegistrator.registerAll(spark)

    try {
      // ── Phase 2.1: Pivot + Spatial Join
      println("\n═══ Phase 2.1: Pivot & Spatial Join ═══")
      val joined = SpatialJoin.runPivotAndJoin(
        spark, cfg.inputDir, cfg.zoningPath, cfg.lulcCategoryCol,
      )

      // ── Phase 2.2: LST Computation
      println("\n═══ Phase 2.2: LST Computation ═══")
      val meta = LSTMath.loadMetadata(spark, metaDir)
      val metaCount = meta.count()
      println(s"  Scene metadata files loaded: $metaCount")
      val withLST = LSTMath.computeLST(joined, meta, cfg)
      println(s"  LST computed: ${withLST.count()} rows")

      // ── Phase 2.3: Target Encoding
      println("\n═══ Phase 2.3: Target Encoding ═══")
      val catCols = Seq("lulc_class", cfg.lulcCategoryCol).distinct
      val availableCats = catCols.filter(withLST.columns.contains)
      val encoded = TargetEncoder.encode(
        withLST, targetCol = "lst", catCols = availableCats, smoothing = cfg.targetSmoothing,
      )
      println(s"  Target encoding complete: ${encoded.columns.length} cols")

      // ── Phase 2.4: Feature Matrix Assembly & Write
      println("\n═══ Phase 2.4: Feature Matrix ═══")
      val matrix = FeatureMatrix.assemble(encoded, cfg)
      FeatureMatrix.write(matrix, cfg.outputDir)

      println("\n═══ Pipeline complete ═══")

    } finally {
      spark.stop()
    }
  }
}
