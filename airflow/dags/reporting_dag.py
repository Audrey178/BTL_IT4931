from airflow.sdk import dag, task, Asset
from datetime import datetime
from airflow.providers.cncf.kubernetes.operators.spark_kubernetes import SparkKubernetesOperator


from utils.spark_utils import load_template_local, ConfigTypes
from utils.config_manager import config_manager

DATASET_GOLD_FDATA = Asset(f"s3a://{config_manager.storage_config.bucket}/delta/gold-fdata")
BUCKET = config_manager.storage_config.bucket
PATH_FACT = f"s3a://{BUCKET}/delta/gold/full-data"
PATH_DAILY = f"s3a://{BUCKET}/delta/gold/daily"
PATH_HOURLY = f"s3a://{BUCKET}/delta/gold/hourly"
PATH_GEO = f"s3a://{BUCKET}/delta/gold/geo-map"

# Define default arguments for the DAG
default_args = {
    'owner': 'data-engineering',
#    'retries': 1,
#    'retry_delay': timedelta(minutes=15),
    'email_on_failure': False,
    'email_on_retry': False,
}

@dag(
    dag_id='2_reporting_pipeline',
    start_date=datetime(2024, 1, 1),
    schedule=[DATASET_GOLD_FDATA],
    catchup=False,
    tags=['reporting', 'spark'],
    default_args=default_args,
)
def reporting_dag():
    def create_report_task(task_id, script_name, output_path, output_env_var):
        @task(task_id=f"tpl_{task_id}")
        def create_tpl() -> dict:
            return load_template_local(config_manager, {ConfigTypes.basic()}).override_with(
                script_name, 
                {"FACT": PATH_FACT, output_env_var: output_path}
            )
        
        return SparkKubernetesOperator(
            kubernetes_conn_id="kubernetes_default",
            task_id=task_id,
            template_spec=create_tpl(),
            namespace="py-spark",
            log_pod_spec_on_failure=True
        )
    s3_daily = create_report_task('submit_s3_daily', 's3_daily.py', PATH_DAILY, 'DAILY')
    s4_hourly = create_report_task('submit_s4_hourly', 's4_hourly.py', PATH_HOURLY, 'HOURLY')
    s6_geo = create_report_task('submit_s6_geo', 's6_geo_map_aqi.py', PATH_GEO, 'GEO')
    
    [s3_daily, s4_hourly, s6_geo]
    
reporting_dag()