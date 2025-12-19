import argparse
import logging 
from pyspark.sql import SparkSession 
from job_file import PythonSparkJob, ParamExtractor, ArgParserParamExtractor, BothEnvAndArgsExtractor, \
    EnvVarParamExtractor
from pyspark.sql.functions import concat_ws, col, lit, avg

logger = logging.getLogger(__name__)
APP_NAME = 'S6_Geo'

class S6_Geo(PythonSparkJob):
    def __init__(self, ps: ParamExtractor, spark_conf: dict = None):
        super().__init__(ps, spark_conf)
        self.fact_path = ps.get_param("fact", required=True)
        self.geo_path = ps.get_param("geo", required=True)
    def run(self):
        spark_session = self.create_spark_session(app_name=APP_NAME)
        self._run_inner(spark_session, self.fact_path, self.geo_path)
    def _run_inner(self, spark_session: SparkSession, fact_path: str, geo_path: str):
        df = spark_session.read.format('delta').load(fact_path)
    
        df_geo = df.withColumn('point', concat_ws(" ", lit("POINT"), col('stopLon'), col('stopLat'), lit(")"))) \
            .groupBy('point') \
                .agg(
                    avg('aqi').alias('avg_aqi')
                )
                
        df_geo.write.format('delta').mode('overwrite').option('overwriteSchema', 'true').save(geo_path)
        spark_session.stop()

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--fact', required = False)
    parser.add_argument('--geo', required = False)
    S6_Geo(BothEnvAndArgsExtractor(ArgParserParamExtractor(parser), EnvVarParamExtractor())).run()

if __name__ == "__main__":
    main()  
    
    