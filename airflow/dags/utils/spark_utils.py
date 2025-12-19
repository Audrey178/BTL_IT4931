import json
import os
from abc import ABC, abstractmethod
from typing import Set, Dict, Callable, Any

import boto3
import yaml
import logging

from .config_manager import ConfigManager

logger = logging.getLogger(__name__)

class Type(ABC):
    @abstractmethod
    def type(self) -> str:
        pass

    def __eq__(self, other):
        return self.type() == other.type()

    def __hash__(self):
        return hash(self.type())

class _Basic(Type):
    def type(self) -> str:
        return "simple"

class _Storage(Type):
    def type(self) -> str:
        return "storage"


_basic = _Basic()
_storage = _Storage()

class ConfigTypes:
    @staticmethod
    def basic() -> Type:
        return _basic

    @staticmethod
    def storage() -> Type:
        return _storage

class Overrider:
    def __init__(self, config_manager: ConfigManager, spark_template: str, config_types: Set[Type], load_dict_func: Callable[[str], dict[str, Any]]):
        self.config_manager = config_manager
        self.spark_template = spark_template
        self.configs = self._get_configs(config_types)
        self.load_dict_func = load_dict_func

    def _get_configs(self, types: Set[Type]) -> Dict[str, str]:
        conf = {}
        for tp in types:
            if tp == ConfigTypes.basic():
                conf.update(self.config_manager.get_spark_configs())
            elif tp == ConfigTypes.storage():
                conf.update(self.config_manager.get_storage_config())
        return conf

    @staticmethod
    def override_template_fields(spark_template: str, configs: dict, job_file_name: str, env_vars: dict, load_dict_func, parent_path) -> dict:
        main_file = f"{parent_path}{job_file_name}"
        spark_image_versions = os.getenv("SPARK_IMAGE_VERSION", "latest")

        spec_dict = load_dict_func(spark_template)

        hadoop_conf = {}
        spark_conf = {}
        for key, value in configs.items():
            if key.startswith("spark.hadoop."):
                hadoop_conf[key.replace("spark.hadoop.", "")] = value
            else:
                spark_conf[key] = value

        spec_dict["hadoopConf"] = hadoop_conf
        spec_dict["mainApplicationFile"] = main_file
        spec_dict["image"] = f"py-spark-spark:{spark_image_versions}"
        spec_dict["driver"]["envVars"] = env_vars

        return {
            "apiVersion": "sparkoperator.k8s.io/v1beta2",
            "kind": "SparkApplication",
            "spec": spec_dict
        }

    def override_with(self, job_file_name: str, env_vars: dict, parent_path : str = "local:///opt/airflow/dags/spark/") -> dict:
        """
        Loads template from s3 (json or yaml), sets spark job file and environment variables
        :param job_file_name: spark job source file
        :param env_vars: to set on spark container
        :param parent_path: by default, it's locally, and it means that script sets spark code to be /opt/airflow/dags/spark/{job_file_name}.
                            You can change it another path or s3 path. In case of s3, you'll probably need to set additional parameters to for master to be
                            able to interact with s3.
                            It's my fault, since I choose to use custom env variable 'STORAGE_' and translate them to spark conf parameter,
                            but SparkKubernetesOperator maybe we'll need aws credentials as they appear in AWS documentation to send the code to spark driver and etc.
        :return: dict containing template stored on s3 with overriding spark code file name and env variables.
        """
        return Overrider.override_template_fields(self.spark_template, self.configs, job_file_name, env_vars, self.load_dict_func, parent_path)

def load_template(config_manager: ConfigManager, config_types: Set[Type] = None, bucket: str = "spark", key: str = "templates/spark_operator_spec.json"):
    """
    Loads template from s3
    :param config_manager: config manager that contains all configs include data to connect to s3 to download template
    :param config_types: tuple of configuration to insert into template spec. One or more between: Type.basic(), Type.storage(), Type.catalog()
    :param bucket: bucket name where spark spec template is stored
    :param key: path in bucket where spark spec template is stored
    :return: Overrider that has only one public method: override_with
    """
    tps = config_types if config_types is not None else (ConfigTypes.basic(), ConfigTypes.storage(), ConfigTypes.catalog())
    s3_client = boto3.client('s3',
         region_name=config_manager.storage_config.region,
         use_ssl=config_manager.storage_config.ssl_enabled,
         endpoint_url=config_manager.storage_config.endpoint,
         aws_access_key_id=config_manager.storage_config.access_key,
         aws_secret_access_key=config_manager.storage_config.secret_key,
     )
    logger.info(f"Loading template from s3://{bucket}/{key}")
    s3_obj = s3_client.get_object(Bucket=bucket, Key=key)

    if key.lower().endswith("yaml") or key.lower().endswith("yml"):
        load_template_function = lambda content: yaml.safe_load(content)
    elif key.lower().endswith("json"):
        load_template_function = lambda content: json.loads(content)
    else:
        raise ValueError(f"Unsupported template format: nor 'json' neither 'yaml'")

    return Overrider(config_manager, s3_obj['Body'].read(), tps, load_template_function)

def load_template_local(config_manager: ConfigManager, config_types: Set[Type] = None, file_path: str = "/spark/templates/spark_operator_spec.json"):
    """
    Loads template from local filesystem
    """
    # Xử lý default config_types giống hàm cũ
    tps = config_types if config_types is not None else (ConfigTypes.basic(), ConfigTypes.storage(), ConfigTypes.catalog())
    
    logger.info(f"Loading template from local file: {file_path}")
    
    # Kiểm tra file có tồn tại không
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Template not found at: {file_path}")

    # Đọc file từ ổ cứng
    with open(file_path, 'rb') as f:  # Dùng 'rb' (read bytes) để khớp với kiểu dữ liệu mà s3 body trả về
        content = f.read()

    # Logic chọn parser (JSON hay YAML)
    if file_path.lower().endswith("yaml") or file_path.lower().endswith("yml"):
        load_template_function = lambda content: yaml.safe_load(content)
    elif file_path.lower().endswith("json"):
        load_template_function = lambda content: json.loads(content)
    else:
        raise ValueError(f"Unsupported template format: nor 'json' neither 'yaml'")

    # Trả về Overrider y hệt hàm load_template cũ
    return Overrider(config_manager, content, tps, load_template_function)

