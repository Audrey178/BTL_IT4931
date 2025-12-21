import argparse
from delta.tables import DeltaTable
from batch.utils import build_spark

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--bronze', required=True)
    parser.add_argument('--gold_fdata', required=True)
    
    args = parser.parse_args()
    
    spark = build_spark('S2_Merge')
    
    bronze_df = spark.read.format("delta").load(args.bronze)
    
    if not DeltaTable.isDeltaTable(spark, args.gold_fdata):
        bronze_df.write.format('delta').mode('overwrite').partitionBy("year", 'month').save(args.gold_fdata)
    
    fdata_table = DeltaTable.forPath(spark, args.gold_fdata)
    
    fdata_table.alias('t').merge(bronze_df.alias('s'), "t.stopId =  s.stopId AND t.datetime = s.datetime") \
        .whenMatchedUpdateAll() \
            .whenNotMatchedInsertAll() \
                .execute()
                
    spark.stop()

if __name__ == "__main__":
    main()