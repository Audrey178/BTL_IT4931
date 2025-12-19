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
        base_bucket = self.gold_fdata_path.split("/delta/")[0]
        self.checkpoint_path = f"{base_bucket}/checkpoints/s2_merge"
    def run(self):
        spark_session = self.create_spark_session(app_name=APP_NAME)
        self._run_inner(spark_session, self.bronze_path, self.gold_fdata_path, self.checkpoint_path)
    def _run_inner(self, spark_session: SparkSession, bronze_path: str, gold_fdata_path: str, checkpoint_path: str):
        def upsert_to_gold(micro_batch_df, batch_id):
            if micro_batch_df.count() == 0:
                return
            
            deduplicated_batch = micro_batch_df.dropDuplicates(["stopId", "datetime"])

            if not DeltaTable.isDeltaTable(spark_session, gold_fdata_path):
                deduplicated_batch.write.format('delta').mode('overwrite').partitionBy("year", 'month').save(gold_fdata_path)
                return

            fdata_table = DeltaTable.forPath(spark_session, gold_fdata_path)
            
            fdata_table.alias('t').merge(
                deduplicated_batch.alias('s'), 
                "t.stopId = s.stopId AND t.datetime = s.datetime"
            ).whenMatchedUpdateAll() \
             .whenNotMatchedInsertAll() \
             .execute()

        bronze_stream = spark_session.readStream.format("delta").load(bronze_path)
        
        query = bronze_stream.writeStream.format('delta').foreachBatch(upsert_to_gold) \
            .option("checkpointLocation", checkpoint_path) \
            .trigger(availableNow=True) \
            .start()
        
        query.awaitTermination()        
        spark_session.stop()

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--bronze', required=False)
    parser.add_argument('--gold_fdata', required=False)    
    S2_Merge(BothEnvAndArgsExtractor(ArgParserParamExtractor(parser), EnvVarParamExtractor())).run()
if __name__ == "__main__":
    main()