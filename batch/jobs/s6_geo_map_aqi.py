import argparse
from pyspark.sql.functions import concat_ws, col, lit, avg
from batch.utils import build_spark

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--fact', required = True)
    parser.add_argument('--geo', required = True)
    
    args = parser.parse_args()
    
    spark = build_spark("step6_geo")
    
    df = spark.read.format('delta').load(args.fact)
    
    df_geo = df.withColumn('point', concat_ws(" ", lit("POINT"), col('stopLon'), col('stopLat'), lit(")"))) \
        .groupBy('point') \
            .agg(
                avg('aqi').alias('avg_aqi')
            )
            
    df_geo.write.format('delta').mode('overwrite').option('overwriteSchema', 'true').save(args.geo)
    spark.stop()
    

if __name__ == "__main__":
    main()  
    
    