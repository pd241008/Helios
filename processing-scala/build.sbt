// ════════════════════════════════════════════════════════════════════
//  Helios — Scala/Spark Aggregation & Processing Layer
// ════════════════════════════════════════════════════════════════════

val scala3Version = "2.13.14"

lazy val root = project
  .in(file("."))
  .settings(
    name         := "helios-processing",
    version      := "0.1.0",
    scalaVersion := scala3Version,
    organization := "com.helios",

    // ── Spark 3.5 (provided in cluster mode, included for local) ──
    libraryDependencies ++= Seq(
      "org.apache.spark" %% "spark-core"   % "3.5.1",
      "org.apache.spark" %% "spark-sql"    % "3.5.1",
      "org.apache.spark" %% "spark-mllib"  % "3.5.1",

      // GeoSpark / Sedona for spatial joins
      "org.apache.sedona" %% "sedona-spark-3.5" % "1.6.0",

      // Testing
      "org.scalatest" %% "scalatest" % "3.2.18" % Test,
    ),

    // ── Assembly settings ─────────────────────────────────────────
    assembly / assemblyMergeStrategy := {
      case PathList("META-INF", "services", _*) => MergeStrategy.filterDistinctLines
      case PathList("META-INF", _*)             => MergeStrategy.discard
      case _                                    => MergeStrategy.first
    },

    // ── JVM options for Spark local mode (Java 17 + Kryo compat) ─
    javaOptions ++= Seq(
      "-Xmx5g",
      "-Xms3g",
      "-XX:+UseG1GC",
      "-XX:MaxGCPauseMillis=200",
      "--add-opens=java.base/sun.nio.ch=ALL-UNNAMED",
      "--add-opens=java.base/java.lang=ALL-UNNAMED",
      "--add-opens=java.base/java.lang.reflect=ALL-UNNAMED",
      "--add-opens=java.base/java.nio=ALL-UNNAMED",
      "--add-opens=java.base/java.io=ALL-UNNAMED",
      "--add-opens=java.base/java.util=ALL-UNNAMED",
    ),
    fork := true,
  )
