import os
import logging
from typing import Dict, Optional, Set
from dataclasses import dataclass
from abc import ABC

logger = logging.getLogger(__name__)

@dataclass
class StorageConfig:
    """Configuration for storage backend."""
    endpoint: Optional[str]
    ssl_enabled: Optional[bool]
    access_key: Optional[str]
    secret_key: Optional[str]
    bucket: Optional[str]
    region: Optional[str]
    path_style_access: Optional[bool]
    credentials_provider: Optional[str]
    
class StorageBackend:
    """Storage backend implementation."""
    
    def __init__(self, config: StorageConfig):
        self.config = config
    
    def get_spark_storage_config(self) -> Dict[str, str]:
        """Get common Spark configuration shared by all storage backends."""
        configs = {
            "spark.hadoop.fs.s3a.impl": "org.apache.hadoop.fs.s3a.S3AFileSystem",
            "spark.hadoop.fs.s3a.access.key": os.getenv("AWS_ACCESS_KEY_ID", "minio"),
            "spark.hadoop.fs.s3a.secret.key": os.getenv("AWS_SECRET_ACCESS_KEY", "minio123"),
            "spark.hadoop.fs.s3a.endpoint": "https://cuong-dev.cloud:9000",
            "spark.hadoop.fs.s3a.connection.ssl.enabled": "true",
            "spark.hadoop.fs.s3a.path.style.access": "true",
            "spark.hadoop.fs.s3a.connection.establish.timeout": "5000",
            "spark.hadoop.fs.s3a.connection.timeout": "10000"
        }

        if self.config.region:
            configs["spark.hadoop.aws.region"] = self.config.region
        
        # Add endpoint if specified
        if self.config.endpoint:
            configs["spark.hadoop.fs.s3a.endpoint"] = self.config.endpoint
        
        # Add credentials if specified
        if self.config.access_key and self.config.secret_key:
            configs.update({
                "spark.hadoop.fs.s3a.access.key": self.config.access_key,
                "spark.hadoop.fs.s3a.secret.key": self.config.secret_key
            })
        
        # Add ssl enabled if specified
        if self.config.path_style_access is not None:
            configs["spark.hadoop.fs.s3a.path.style.access"] = str(self.config.path_style_access).lower()

        # Add path style access if specified
        if self.config.ssl_enabled is not None:
            configs["spark.hadoop.fs.s3a.connection.ssl.enabled"] = str(self.config.ssl_enabled).lower()
        
        # Add credentials provider if specified
        if self.config.credentials_provider:
            configs["spark.hadoop.fs.s3a.aws.credentials.provider"] = self.config.credentials_provider

        return configs
    
class ConfigManager:
    """Manages storage and catalog configuration using polymorphism."""
    
    def __init__(self):
        self.storage_config = self._load_storage_config()
        self.storage_backend = self._create_storage_backend(self.storage_config)
   
    def _load_storage_config(self) -> StorageConfig:
        """Load storage configuration from environment variables."""
        # Common validation - bucket and catalog type are required
        bucket_env = os.getenv('STORAGE_BUCKET')
        if not bucket_env:
            raise ValueError("STORAGE_BUCKET must be set for storage configuration")

        # Parse storage ssl enabled
        storage_ssl_enabled_str = os.getenv('STORAGE_ENDPOINT_SSL_ENABLE')
        storage_ssl_enabled = None
        if storage_ssl_enabled_str:
            storage_ssl_enabled = storage_ssl_enabled_str.lower() in ('true', '1', 'yes', 'on')

        # Parse path style access
        path_style_access_str = os.getenv('STORAGE_PATH_STYLE_ACCESS')
        path_style_access = None
        if path_style_access_str:
            path_style_access = path_style_access_str.lower() in ('true', '1', 'yes', 'on')

        return StorageConfig(
            endpoint=os.getenv('STORAGE_ENDPOINT'),
            access_key=os.getenv('AWS_ACCESS_KEY_ID'),
            secret_key=os.getenv('AWS_SECRET_ACCESS_KEY'),
            bucket=bucket_env,
            region=os.getenv('AWS_REGION', 'us-east-1'),
            path_style_access=path_style_access,
            credentials_provider=os.getenv('STORAGE_CREDENTIALS_PROVIDER'),
            ssl_enabled=storage_ssl_enabled
        )

    def _create_storage_backend(self, config: StorageConfig) -> StorageBackend:
        """Create storage backend based on configuration."""
        return StorageBackend(config)

    def get_spark_configs(self) -> Dict[str, str]:
        configs = {
            "spark.sql.adaptive.enabled": "true",
            "spark.sql.adaptive.coalescePartitions.enabled": "true",
            "spark.sql.adaptive.skewJoin.enabled": "true",
            "spark.sql.adaptive.localShuffleReader.enabled": "true",
            "spark.sql.adaptive.optimizeSkewedJoin.enabled": "true",
            "spark.sql.adaptive.forceApply": "true"
        }

        if os.getenv("SPARK_MASTER_URL") is not None:
            configs["spark.master"] = os.getenv("SPARK_MASTER_URL")

        return configs
    
    def get_storage_config(self) -> Dict[str, str]:
        """Get warehouse paths for the current storage backend."""
        return {
            "spark.hadoop.fs.s3a.access.key": "minio",
            "spark.hadoop.fs.s3a.secret.key": "minio123",
            "spark.hadoop.fs.s3a.endpoint": "https://cuong-dev.cloud:9000",
            "spark.hadoop.fs.s3a.path.style.access": "true",
            "spark.hadoop.fs.s3a.connection.ssl.enabled": "true"
        }


    def get_all_configs(self) -> Dict[str, str]:
        return {**self.get_spark_configs(), **self.get_storage_config()}

# Global config manager instance
config_manager = ConfigManager()
    