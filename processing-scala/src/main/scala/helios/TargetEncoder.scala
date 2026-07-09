package helios

import org.apache.spark.sql.{DataFrame}
import org.apache.spark.sql.functions._

object TargetEncoder {

  def encode(
    df:        DataFrame,
    targetCol: String,
    catCols:   Seq[String],
    smoothing: Double = 10.0
  ): DataFrame = {
    val globalMean = df.agg(avg(col(targetCol))).first().getDouble(0)
    println(s"  Target-encoding $catCols; global_mean=${"%.4f".format(globalMean)} smoothing=$smoothing")

    var result = df
    for (catCol <- catCols) {
      val catStats = df
        .groupBy(catCol)
        .agg(
          avg(col(targetCol)).as("_cat_mean"),
          count(col(targetCol)).as("_cat_count")
        )

      val encodedColName = s"${catCol}_encoded"

      result = result
        .join(catStats, Seq(catCol), "left")
        .withColumn(encodedColName,
          (col("_cat_count") * col("_cat_mean") + lit(smoothing) * lit(globalMean)) /
          (col("_cat_count") + lit(smoothing))
        )
        .drop("_cat_mean", "_cat_count")

      println(s"    $catCol → $encodedColName")
    }

    result
  }

  def encodeFolded(
    df:        DataFrame,
    targetCol: String,
    catCols:   Seq[String],
    k:         Int       = 5,
    smoothing: Double    = 10.0
  ): DataFrame = {
    if (k <= 1) {
      println(s"  k=$k <= 1, using global encoding instead")
      return encode(df, targetCol, catCols, smoothing)
    }

    println(s"  K-fold encoding: k=$k target=$targetCol cats=$catCols smoothing=$smoothing")

    val dfWithFold = df
      .withColumn("_row_id", monotonicallyIncreasingId())
      .withColumn("_fold", abs(hash(col("_row_id"))) % k)
      .drop("_row_id")
    dfWithFold.cache()
    val totalRows = dfWithFold.count()
    println(s"    Cached $totalRows rows for fold encoding")

    var result = dfWithFold
    for (catCol <- catCols) {
      val encodedCol = s"${catCol}_encoded"
      println(s"    Encoding $catCol ...")

      var accum: Option[DataFrame] = None

      for (fold <- 0 until k) {
        val train = dfWithFold.filter(col("_fold") =!= lit(fold))
        val test  = dfWithFold.filter(col("_fold") === lit(fold))

        val globalMean = train.agg(avg(col(targetCol))).first().getDouble(0)

        val catStats = train
          .groupBy(catCol)
          .agg(
            avg(col(targetCol)).as("_cat_mean"),
            count(col(targetCol)).as("_cat_count")
          )

        val encodedTest = test
          .join(catStats, Seq(catCol), "left")
          .withColumn(encodedCol,
            (
              coalesce(col("_cat_count").cast("double"), lit(0.0)) * coalesce(col("_cat_mean"), lit(globalMean)) +
              lit(smoothing) * lit(globalMean)
            ) / (
              coalesce(col("_cat_count").cast("double"), lit(0.0)) + lit(smoothing)
            )
          )
          .drop("_cat_mean", "_cat_count")

        accum = accum match {
          case Some(a) => Some(a.union(encodedTest))
          case None    => Some(encodedTest)
        }
      }

      result = accum.get
      println(s"    Done encoding $catCol")
    }

    result.drop("_fold")
  }
}
