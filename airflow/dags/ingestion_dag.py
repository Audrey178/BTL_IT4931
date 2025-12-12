"""
Airflow 3.0 for Spark job using modern decorators
"""
import logging
from datetime import datetime

from airflow.sdk import dag, task
from airflow.providers.cncf.kubernetes.operators.spark_kubernetes import SparkKubernetesOperator

from utils.spark_utils import load_template_local, ConfigTypes
from utils.config_manager import config_manager

logger = logging.getLogger(__name__)

# Define default arguments for the DAG
default_args = {
    'owner': 'data-engineering',
#    'retries': 1,
#    'retry_delay': timedelta(minutes=15),
    'email_on_failure': False,
    'email_on_retry': False,
}

@dag(
    dag_id='1_ingestion_data',
    description='Spark Pipeline: S1_ETL -> S2_Merge',
    start_date=datetime(2024, 1, 1),
    catchup=False,
    tags=['spark', 's3', 'k8s'],
    default_args=default_args
)
def spark_job_dag():
    @task
    def create_etl_template() -> dict:
        return (
            load_template_local(config_manager, {ConfigTypes.basic()}, 
            file_path="/spark/templates/spark_operator_spec.json")
            .override_with("s1_etl.py",
               {
                    "INPUT": f"s3a://{config_manager.storage_config.bucket}/sensor-data",
                    "BRONZE": f"s3a://{config_manager.storage_config.bucket}/delta/bronze"
                }
            )
        )
    
    @task
    def create_merge_template() -> dict:
        return (
            load_template_local(
                config_manager, 
                {ConfigTypes.basic()}, 
                file_path="/spark/templates/spark_operator_spec.json"
            )
            .override_with("s2_merge.py",
               {
                    "BRONZE": f"s3a://{config_manager.storage_config.bucket}/delta/bronze",
                    "GOLD_FDATA": f"s3a://{config_manager.storage_config.bucket}/delta/gold/full-data"
                }
            )
        )

    etl_spec = create_etl_template()
    merge_spec = create_merge_template()

    submit_etl = SparkKubernetesOperator(
        kubernetes_conn_id="kubernetes_default",
        task_id='submit_s1_etl',
        template_spec=etl_spec,
        namespace="py-spark",
        log_pod_spec_on_failure=True
    )
    
    submit_merge = SparkKubernetesOperator(
        kubernetes_conn_id="kubernetes_default",
        task_id='submit_s2_merge',
        template_spec=merge_spec,
        namespace="py-spark",
        log_pod_spec_on_failure=True
    )

    submit_etl >> submit_merge

# Create the DAG
spark_job_dag()