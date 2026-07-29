package helios

import org.apache.spark.sql.SparkSession
import org.apache.sedona.sql.utils.SedonaSQLRegistrator

object Main {

  def main(args: Array[String]): Unit = {
    val cfg = PipelineConfig.fromArgs(args)
    val metaDir = if (cfg.metadataDir.isEmpty) s"${cfg.inputDir}/landsat" else cfg.metadataDir

    // Validate year ranges before any Spark work — fail fast on degenerate split.
    cfg.validateYearRanges()

    println(s"═══ Helios Processing Pipeline ═══")
    println(s"  Input:   ${cfg.inputDir}")
    println(s"  Output:  ${cfg.outputDir}")
    println(s"  Zoning:  ${cfg.zoningPath}")
    println(s"  Years:   train=${cfg.trainYearStart}-${cfg.trainYearEnd}  test=${cfg.testYearStart}-${cfg.testYearEnd}")
    if (cfg.sampleRate < 1.0) {
      println(s"  ╔══════════════════════════════════════════════════════════════╗")
      println(s"  ║  RUNNING AT SAMPLE RATE ${cfg.sampleRate} — NOT A PIPELINE VALIDATION  ║")
      println(s"  ║  Full resolution (sample-rate 1.0) required for spatial     ║")
      println(s"  ║  analysis fidelity. Sampling belongs at the ML training     ║")
      println(s"  ║  stage only. Any metrics from this run are approximate.     ║")
      println(s"  ╚══════════════════════════════════════════════════════════════╝")
    }

    val spark = SparkSession.builder()
      .appName("helios-processing")
      .master("local[4]")
      .config("spark.sql.adaptive.enabled", "true")
      .config("spark.sql.parquet.compression.codec", "zstd")
      .config("spark.serializer", "org.apache.spark.serializer.JavaSerializer")
      .config("spark.sql.shuffle.partitions", "400")
      .config("spark.driver.memory", "5g")
      .config("spark.executor.memory", "5g")
      .config("spark.memory.fraction", "0.85")
      .config("spark.memory.storageFraction", "0.2")
      .config("spark.sql.files.maxPartitionBytes", "33554432")
      .config("spark.sql.shuffle.spill.compress", "true")
      .getOrCreate()

    // spark.sparkContext.setLogLevel("WARN")

    SedonaSQLRegistrator.registerAll(spark)

    try {
      val p21Path = s"${cfg.outputDir}/_intermediate/phase21_joined"
      val p22Path = s"${cfg.outputDir}/_intermediate/phase22_with_lst"
      val p23Path = s"${cfg.outputDir}/_intermediate/phase23_encoded"

      var encoded = if (new java.io.File(s"$p23Path/_SUCCESS").exists()) {
        println(s"\n═══ Skipping Phases 2.1-2.3: Found existing Phase 2.3 output ═══")
        spark.read.parquet(p23Path)
      } else { null }

      if (encoded == null) {
        var withLST = if (new java.io.File(s"$p22Path/_SUCCESS").exists()) {
          println(s"\n═══ Skipping Phases 2.1-2.2: Found existing Phase 2.2 output ═══")
          spark.read.parquet(p22Path)
        } else { null }

        if (withLST == null) {
          var joined = if (new java.io.File(s"$p21Path/_SUCCESS").exists()) {
            println(s"\n═══ Skipping Phase 2.1: Found existing Phase 2.1 output ═══")
            spark.read.parquet(p21Path)
          } else { null }

          if (joined == null) {
            println("\n═══ Phase 2.1: Pivot & Spatial Join ═══")
            val sceneDir = new java.io.File(s"${cfg.inputDir}/landsat")
            val sceneFiles = sceneDir.listFiles()
              .filter(f => f.getName.endsWith(".parquet") && f.isFile)
              .sortBy(_.getName)
            println(s"  Scene parquet files found: ${sceneFiles.length}")
            sceneFiles.foreach { f =>
              println(s"    ${f.getName} (${"%.1f".format(f.length() / 1e6)} MB)")
            }

            joined = SpatialJoin.runPivotAndJoin(
              spark, cfg.inputDir, cfg.zoningPath, cfg.lulcCategoryCol, cfg.sampleRate,
            )

            val zoneDist = joined.groupBy(cfg.lulcCategoryCol).count().orderBy("count").collect()
            println("  Per-zone pixel counts:")
            zoneDist.foreach { r =>
              println(s"    ${r.get(0)} = ${r.get(1)}")
            }
            val totalJoined = zoneDist.map(_.getLong(1)).sum
            val totalZoned = zoneDist.filter(_.get(0) != null).map(_.getLong(1)).sum
            val outsideAll = totalJoined - totalZoned
            println(s"  Pixels inside any zone: $totalZoned")
            println(s"  Pixels outside all zones: $outsideAll")

            joined.write
              .mode("overwrite")
              .option("compression", "zstd")
              .parquet(p21Path)
            println(s"  Saved Phase 2.1 intermediate: $p21Path")
          }

          println("\n═══ Phase 2.2: LST Computation ═══")
          val meta = LSTMath.loadMetadata(spark, metaDir)
          val metaCount = meta.count()
          println(s"  Scene metadata files loaded: $metaCount")
          withLST = LSTMath.computeLST(joined, meta, cfg)
          
          try { joined.unpersist() } catch { case _: Throwable => }

          withLST.cache()
          val lstCount = withLST.count()
          println(s"  LST computed: $lstCount rows")

          val splitDist = withLST.groupBy("has_thermal_split").count().collect()
          println("  has_thermal_split distribution:")
          splitDist.foreach { r =>
            println(s"    ${r.get(0)} = ${r.get(1)}")
          }

          withLST.write
            .mode("overwrite")
            .option("compression", "zstd")
            .parquet(p22Path)
          println(s"  Saved Phase 2.2 intermediate: $p22Path")
        }

        withLST.cache()

        println("\n═══ Phase 2.3: Target Encoding ═══")
        val catCols = Seq("lulc_class", cfg.lulcCategoryCol).distinct
        val availableCats = catCols.filter(withLST.columns.contains)
        encoded = TargetEncoder.encode(
          withLST, targetCol = "lst", catCols = availableCats, smoothing = cfg.targetSmoothing,
        )
        println(s"  Target encoding complete: ${encoded.columns.length} cols")

        encoded.write
          .mode("overwrite")
          .option("compression", "zstd")
          .parquet(p23Path)
        println(s"  Saved Phase 2.3 intermediate: $p23Path")

        withLST.unpersist()
      }


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
