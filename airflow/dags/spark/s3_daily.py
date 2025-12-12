import logging 
from pyspark.sql import SparkSession 
import argparse
from pyspark.sql.functions import avg, to_date
from job_file import PythonSparkJob, ParamExtractor, ArgParserParamExtractor, BothEnvAndArgsExtractor, \
    EnvVarParamExtractor
    
logger = logging.getLogger(__name__)
APP_NAME = 'S3_Daily'

class S3_Daily(PythonSparkJob):
    def __init__(self, ps: ParamExtractor, spark_conf: dict = None):
        super().__init__(ps, spark_conf)
        self.fact_path = ps.get_param("fact", required=True)
        self.daily_path = ps.get_param("daily", required=True)
    def run(self):
        spark_session = self.create_spark_session(app_name=APP_NAME)
        self._run_inner(spark_session, self.fact_path, self.daily_path)
    def _run_inner(self, spark_session: SparkSession, fact_path: str, daily_path: str):
        df = spark_session.read.format('delta').load(fact_path)
    
        df_daily = df.withColumn("date", to_date(df.datetime)) \
            .groupBy("locationName", "date") \
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
            
        df_daily.write.format('delta').mode('overwrite').option('overwriteSchema', 'true').save(daily_path)
        spark_session.stop()
        
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fact", required=False)
    parser.add_argument("--daily", required=False)
    S3_Daily(BothEnvAndArgsExtractor(ArgParserParamExtractor(parser), EnvVarParamExtractor())).run()
    
if __name__ == "__main__":
    main()  