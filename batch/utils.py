import os
from pyspark.sql import SparkSession
from pyspark import SparkContext

os.environ["SPARK_HOME"] = "/home/trang/spark"

def load_config(spark_context: SparkContext):
    spark_context._jsc.hadoopConfiguration().set("fs.s3a.access.key", os.getenv("AWS_ACCESS_KEY_ID", "minio"))
    spark_context._jsc.hadoopConfiguration().set("fs.s3a.secret.key",
    os.getenv("AWS_SECRET_ACCESS_KEY", "minio123"))
    spark_context._jsc.hadoopConfiguration().set("fs.s3a.endpoint", "https://cuong-dev.cloud:9000")
    spark_context._jsc.hadoopConfiguration().set("fs.s3a.connection.ssl.enabled", "false")
    spark_context._jsc.hadoopConfiguration().set("fs.s3a.path.style.access", "true")
    spark_context._jsc.hadoopConfiguration().set("fs.s3a.attempts.maximum", "1")
    spark_context._jsc.hadoopConfiguration().set("fs.s3a.connection.establish.timeout", "5000")
    spark_context._jsc.hadoopConfiguration().set("fs.s3a.connection.timeout", "10000")
    spark_context._jsc.hadoopConfiguration().set("fs.s3a.impl", "org.apache.hadoop.fs.s3a.S3AFileSystem")

def build_spark(app_name: str):
    spark = SparkSession.builder \
            .appName(app_name) \
                .config("spark.sql.extensions", "io.delta.sql.DeltaSparkSessionExtension") \
                    .config("spark.sql.catalog.spark_catalog", "org.apache.spark.sql.delta.catalog.DeltaCatalog") \
                        .getOrCreate()
    spark.conf.set("spark.sql.legacy.timeParserPolicy", "LEGACY")
    print(spark.sparkContext._conf.get("spark.jars"))
    
    load_config(spark.sparkContext)
    return spark
                        
