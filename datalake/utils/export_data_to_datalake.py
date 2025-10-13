import pandas as pd
import os
from minio import Minio
from helpers import load_cfg
from glob import glob
import argparse


CFG_FILE = "./datalake/utils/config.yaml"

def upload_local_directory_to_minio(minio_client, local_path, bucket_name, minio_path):
    assert os.path.isdir(local_path)

    for local_file in glob(local_path + "/**"):
        if not os.path.isfile(local_file):
            upload_local_directory_to_minio(
                minio_client,
                local_file,
                bucket_name,
                minio_path + "/" + os.path.basename(local_file),
            )
        else:
            remote_path = os.path.join(minio_path, local_file[1 + len(local_path) :])
            minio_client.fput_object(bucket_name, remote_path, local_file)

def export_data_to_datalake_minio(file_format: str = 'parquet'):
    if file_format not in ['csv', 'parquet']:
        raise ValueError("Unsupported file format. Please use 'csv' or 'parquet'.")

    config = load_cfg(CFG_FILE)
    datalake_cfg = config['datalake']
    bus_data_cfg = config['datalake_bus_data']
    
    # Initialize MinIO client
    minio_client = Minio(   
        endpoint=datalake_cfg['endpoint'],
        access_key=datalake_cfg['access_key'],
        secret_key=datalake_cfg['secret_key'],
        secure=False
    )
    
    # Create bucket if it doesn't exist
    found = minio_client.bucket_exists(bucket_name=datalake_cfg['bucket_name'])
    if not found:
        minio_client.make_bucket(bucket_name=datalake_cfg['bucket_name'])
    else:
        print(f"Bucket '{datalake_cfg['bucket_name']}' already exists.")
    
    # Upload files from local directory to MinIO
    upload_local_directory_to_minio(minio_client=minio_client,
                                    local_path=bus_data_cfg['folder_path'],
                                    bucket_name=datalake_cfg['bucket_name'],
                                    minio_path=datalake_cfg['folder_name'])
    
    
if __name__ == "__main__":
    export_data_to_datalake_minio()