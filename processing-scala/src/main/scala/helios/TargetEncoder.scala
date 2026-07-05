package helios

import org.apache.spark.sql.{DataFrame, SparkSession}
import org.apache.spark.sql.expressions.Window
import org.apache.spark.sql.functions._

/**
 * Target Encoding for high-cardinality categorical features.
 *
 * This is critical for features like LULC class (18 categories) and
 * local zoning maps where one-hot encoding would explode dimensionality.
 *
 * The encoder replaces each category with a smoothed mean of the target
 * variable, blending the category mean with the global mean to prevent
 * overfitting on rare classes.
 *
 * Formula:
 *   encoded = (count × category_mean + smoothing × global_mean) / (count + smoothing)
 *
 * Where:
 *   - count       = number of rows with this category value
 *   - category_mean = mean of target within this category
 *   - global_mean   = mean of target across all rows
 *   - smoothing     = regularization parameter (higher = more shrinkage)
 */
object TargetEncoder {

  /**
   * Applies smoothed target encoding to one or more categorical columns.
   *
   * @param df        Input DataFrame with target and categorical columns.
   * @param targetCol Name of the continuous target column (e.g., "B10_TIR").
   * @param catCols   Categorical columns to encode (e.g., Seq("lulc_class")).
   * @param smoothing Regularization strength. Higher values shrink rare
   *                  categories toward the global mean more aggressively.
   * @return DataFrame with new `{catCol}_encoded` columns replacing the originals.
   */
  def encode(
    df:        DataFrame,
    targetCol: String,
    catCols:   Seq[String],
    smoothing: Double = 10.0
  ): DataFrame = {

    // Global mean of the target.
    val globalMean = df.agg(avg(col(targetCol))).first().getDouble(0)

    var result = df

    for (catCol <- catCols) {
      // Per-category statistics.
      val catStats = df
        .groupBy(catCol)
        .agg(
          avg(col(targetCol)).as("_cat_mean"),
          count(col(targetCol)).as("_cat_count")
        )

      val encodedColName = s"${catCol}_encoded"

      // Join stats back and compute smoothed encoding.
      result = result
        .join(catStats, Seq(catCol), "left")
        .withColumn(encodedColName,
          (col("_cat_count") * col("_cat_mean") + lit(smoothing) * lit(globalMean)) /
          (col("_cat_count") + lit(smoothing))
        )
        .drop("_cat_mean", "_cat_count")

      println(s"  ✓ Target-encoded '$catCol' → '$encodedColName' (smoothing=$smoothing, global_mean=${"%.4f".format(globalMean)})")
    }

    result
  }

  /**
   * K-Fold target encoding to prevent target leakage during training.
   *
   * Splits data into K folds; for each fold, computes the encoding
   * from the remaining K-1 folds only. This is the production-grade
   * approach for model training.
   *
   * TODO(production): Implement fold-based encoding using a fold column
   * or monotonically_increasing_id() % k for fold assignment.
   */
  def encodeFolded(
    df:        DataFrame,
    targetCol: String,
    catCols:   Seq[String],
    k:         Int       = 5,
    smoothing: Double    = 10.0
  ): DataFrame = {
    // Placeholder — delegates to simple encoding for now.
    println(s"  ⚠ K-fold encoding not yet implemented (k=$k), falling back to global encoding")
    encode(df, targetCol, catCols, smoothing)
  }
}
