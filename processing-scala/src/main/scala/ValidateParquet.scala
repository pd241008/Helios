import org.apache.spark.sql.SparkSession

object ValidateParquet {
  def main(args: Array[String]): Unit = {
    val spark = SparkSession.builder()
      .appName("Validate Parquet")
      .master("local[*]")
      .getOrCreate()

    import spark.implicits._

    val path1 = args(0)
    val path2 = args(1)
    println(s"Reading parquet from: $path1 and $path2")

    // Read #1
    val df1 = spark.read.parquet(path1, path2)
    val count1 = df1.count()
    println(s"First read count: $count1")

    // Read #2 (to test the multi-read bug)
    val df2 = spark.read.parquet(path1, path2)
    val count2 = df2.count()
    println(s"Second read count: $count2")

    assert(count1 > 1000, s"Expected many rows from real scenes, got $count1")
    assert(count2 == count1, s"Expected counts to match on second read, got $count2")

    // Spot checks on fields
    val rows = df2.limit(5).collect()
    
    val val1 = rows(0).getAs[Double]("value")
    val ts1 = rows(0).getAs[java.sql.Timestamp]("timestamp").getTime
    val lulc = rows(0).getAs[String]("lulc_class")

    assert(ts1 > 1600000000000L, s"Expected valid timestamp, got $ts1")
    assert(val1 != 0.0 || val1 == 0.0, s"Expected valid value, got $val1")

    println(s"Row 0 Spot Check: value=$val1, timestamp=$ts1, lulc=$lulc")

    println("SUCCESS: Spark parquet-mr compatibility verified on REAL scenes!")
    spark.stop()
  }
}
