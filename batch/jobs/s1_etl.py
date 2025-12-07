import argparse
import uuid
from batch.utils import build_spark

from pyspark.sql import types 
from pyspark.sql.functions import col, to_timestamp, when, lit, year, month, dayofmonth, hour, coalesce
from pyspark.sql.types import StringType

APP_NAME = 'Job 1: ETL'

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, help='raw input path')
    parser.add_argument("--bronze", required=True, help='bronze path (after ETL)')
    args = parser.parse_args()
    
    spark = build_spark(APP_NAME)
    
    schema = types.StructType([types.StructField('stopId', types.StringType(), True),
                     types.StructField('countryIso', types.StringType(), True), 
                     types.StructField('countryUrl', types.StringType(), True), 
                     types.StructField('stopName', types.StringType(), True), 
                     types.StructField('stopTypeGroup', types.StringType(), True), 
                     types.StructField('stopLat', types.DoubleType(), True), 
                     types.StructField('stopLon', types.DoubleType(), True), 
                     types.StructField('stopDesc', types.StringType(), True), 
                     types.StructField('datetime', types.StringType(), True), 
                     types.StructField('tags', types.StructType([types.StructField('name', types.StringType(), True)]), True), 
                     types.StructField('carbon_monoxide', types.DoubleType(), True), 
                     types.StructField('carbon_dioxide', types.DoubleType(), True), 
                     types.StructField('nitrogen_dioxide', types.DoubleType(), True), 
                     types.StructField('sulphur_dioxide', types.DoubleType(), True), 
                     types.StructField('uv_index_clear_sky', types.DoubleType(), True), 
                     types.StructField('uv_index', types.DoubleType(), True), 
                     types.StructField('temperature_2m', types.DoubleType(), True), 
                     types.StructField('relative_humidity_2m', types.DoubleType(), True), 
                     types.StructField('precipitation', types.DoubleType(), True), 
                     types.StructField('windspeed_10m', types.DoubleType(), True), 
                     types.StructField('winddirection_10m', types.DoubleType(), True)])
    
    df = spark.read \
          .option("header", "true") \
          .schema(schema) \
          .parquet(args.input)
    
    
    df = df.withColumn("datetime", to_timestamp("datetime")) \
        .withColumn("locationName", col('tags.name')).drop('tags') \
            .withColumn("stopDesc",when((col("stopDesc").isNull()) | (col("stopDesc") == ""), lit("unknown")).otherwise(col("stopDesc"))) \
    
    # Handle clean data
    df = df.fillna({
        "stopId": str(uuid.uuid4()),
        "locationName": "unknown",
        "carbon_monoxide": 0.0,
        "carbon_dioxide": 0.0,
        "nitrogen_dioxide": 0.0,
        "sulphur_dioxide": 0.0,
        "uv_index": 0.0,
        "temperature_2m": 0.0,
        "relative_humidity_2m": 0.0,
        "precipitation": 0.0,
        "windspeed_10m": 0.0,
        "winddirection_10m": 0.0
    })      
    
    # Handle datetime 
    df = df.withColumn('year', year(col('datetime'))) \
        .withColumn('month', month(col('datetime'))) \
            .withColumn('day', dayofmonth(col('datetime'))) \
                .withColumn('hour', hour(col('datetime'))) 
                
    # compute simple AQI 
    df = df.withColumn("aqi",
        coalesce(col("carbon_monoxide"), lit(0.0)) * lit(0.4) +
        coalesce(col("nitrogen_dioxide"), lit(0.3)) * lit(1.0) +
        coalesce(col("sulphur_dioxide"), lit(0.3)) * lit(1.0)
    )
                
    df.write.format('delta').mode('overwrite').option("overwriteSchema", 'true')\
        .partitionBy('year', 'month', 'day').save(args.bronze)
    
    spark.stop() 
        

if __name__ == "__main__":
    main()
                
    
    