import argparse
from pyspark.sql.functions import avg, to_date, date_trunc
from batch.utils import build_spark

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fact", required=True)
    parser.add_argument("--hourly", required=True)
    args = parser.parse_args()

    spark = build_spark("step4_hourly")
    
    df = spark.read.format('delta').load(args.fact)
    
    df_daily = df.withColumn("hour", date_trunc("hour", df.datetime)) \
        .groupBy("locationName", "hour") \
        .agg(
            avg("carbon_monoxide").alias("avg_co"),
            avg("nitrogen_dioxide").alias("avg_no2"),
            avg("sulphur_dioxide").alias("avg_so2"),
            avg("carbon_dioxide").alias("avg_co2"),
            avg("temperature_2m").alias("avg_temp"),
            avg("relative_humidity_2m").alias("avg_humidity"),
            avg("precipitation").alias("avg_precipitation"),
            avg("windspeed_10m").alias("avg_windspeed"),
            avg("aqi").alias("avg_aqi"),
        )
        
    df_daily.write.format('delta').mode('overwrite').option('overwriteSchema', 'true').save(args.hourly)
    spark.stop()


if __name__ == "__main__":
    main()  
    
    
    