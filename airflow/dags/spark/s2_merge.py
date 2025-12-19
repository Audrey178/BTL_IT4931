import logging 
from pyspark.sql import SparkSession 
import argparse
from delta.tables import DeltaTable
from job_file import PythonSparkJob, ParamExtractor, ArgParserParamExtractor, BothEnvAndArgsExtractor, \
    EnvVarParamExtractor
    
logger = logging.getLogger(__name__)
APP_NAME = 'S2_Merge'

class S2_Merge(PythonSparkJob):
    def __init__(self, ps: ParamExtractor, spark_conf: dict = None):
        super().__init__(ps, spark_conf)
        self.bronze_path = ps.get_param("bronze", required=True)
        self.gold_fdata_path = ps.get_param("gold-fdata", required=True)
    def run(self):
        spark_session = self.create_spark_session(app_name=APP_NAME)
        self._run_inner(spark_session, self.bronze_path, self.gold_fdata_path)
    def _run_inner(self, spark_session: SparkSession, bronze_path: str, gold_fdata_path: str):
        bronze_df = spark_session.read.format("delta").load(bronze_path)
    
        if not DeltaTable.isDeltaTable(spark_session, gold_fdata_path):
            bronze_df.write.format('delta').mode('overwrite').partitionBy("year", 'month').save(gold_fdata_path)
        
        fdata_table = DeltaTable.forPath(spark_session, gold_fdata_path)
        
        fdata_table.alias('t').merge(bronze_df.alias('s'), "t.stopId =  s.stopId AND t.datetime = s.datetime") \
            .whenMatchedUpdateAll() \
                .whenNotMatchedInsertAll() \
                    .execute()
                    
        spark_session.stop()

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--bronze', required=False)
    parser.add_argument('--gold_fdata', required=False)    
    S2_Merge(BothEnvAndArgsExtractor(ArgParserParamExtractor(parser), EnvVarParamExtractor())).run()
if __name__ == "__main__":
    main()