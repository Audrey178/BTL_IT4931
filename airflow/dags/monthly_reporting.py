from airflow.sdk import dag, task
from airflow.providers.cncf.kubernetes.operators.spark_kubernetes import SparkKubernetesOperator
from datetime import datetime
from utils.spark_utils import load_template_local, ConfigTypes
from utils.config_manager import config_manager

BUCKET = config_manager.storage_config.bucket
PATH_FACT = f"s3a://{BUCKET}/delta/gold/full-data"
PATH_MONTHLY = f"s3a://{BUCKET}/delta/gold/monthly"

# Define default arguments for the DAG
default_args = {
    'owner': 'data-engineering',
#    'retries': 1,
#    'retry_delay': timedelta(minutes=15),
    'email_on_failure': False,
    'email_on_retry': False,
}

@dag(
    dag_id='3_monthly_reporting',
    start_date=datetime(2024, 1, 1),
    schedule="@monthly",
    catchup=False,
    tags=['reporting', 'monthly'],
    default_args=default_args
)
def monthly_dag():
    
    @task
    def tpl_s5() -> dict:
        return load_template_local(config_manager, {ConfigTypes.basic()}).override_with(
            "s5_monthly.py", 
            {"FACT": PATH_FACT, "MONTHLY": PATH_MONTHLY}
        )

    s5 = SparkKubernetesOperator(
        kubernetes_conn_id="kubernetes_default",
        task_id='submit_s5_monthly',
        template_spec=tpl_s5(),
        namespace="py-spark",
        log_pod_spec_on_failure=True
    )

    s5

monthly_dag()