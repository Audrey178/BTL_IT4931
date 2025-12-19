from airflow import DAG, Asset
from airflow.providers.standard.operators.python import PythonOperator
from airflow.models import Variable
from datetime import datetime, timedelta
import pandas as pd
import os
import openmeteo_requests
import requests_cache
from retry_requests import retry
from concurrent.futures import ThreadPoolExecutor, as_completed
import time
import random
from pendulum import timezone

from utils.config_manager import config_manager

local_tz = timezone("Asia/Ho_Chi_Minh")

# --- CẤU HÌNH MINIO ---
MINIO_ENDPOINT = config_manager.storage_config.endpoint
MINIO_ACCESS_KEY = config_manager.storage_config.access_key
MINIO_SECRET_KEY = config_manager.storage_config.secret_key
BUCKET_NAME = config_manager.storage_config.bucket
DATASET_SENSOR_DATA = Asset(f"s3a://{config_manager.storage_config.bucket}/sensor-data")

# Folder đầu vào (Do DAG simulation sinh ra)
INPUT_PREFIX = "bus-data"
# Folder đầu ra (Nơi Spark Job 1 đang lắng nghe)
OUTPUT_PREFIX = "sensor-data"

# --- OPEN-METEO SETUP ---
cache_session = requests_cache.CachedSession('.cache', expire_after=3600)
retry_session = retry(cache_session, retries=5, backoff_factor=0.2)
openmeteo = openmeteo_requests.Client(session=retry_session)

def gen_fake():
    return {
        "carbon_monoxide": random.randint(420, 800),
        "carbon_dioxide": random.randint(350, 500),
        "nitrogen_dioxide": random.uniform(10, 80),
        "sulphur_dioxide": random.uniform(5, 120),
        "uv_index_clear_sky": random.uniform(0, 1),
        "uv_index": random.uniform(0, 1),
        "temperature_2m": random.uniform(10, 40),
        "relative_humidity_2m": random.randint(40, 100),
        "precipitation": random.uniform(0, 20),
        "windspeed_10m": random.uniform(0, 15),
        "winddirection_10m": random.uniform(0, 360)
    }


def fetch_air_weather(row):
    lat = row['stopLat']
    lon = row['stopLon']
    date = row['datetime']
    
    if pd.isna(lat) or pd.isna(lon):
        return row.to_dict()

    dt = pd.to_datetime(date, utc=True)
    start_time = (dt - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M")
    end_time = (dt + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M")

    try: 
        url_air = "https://air-quality-api.open-meteo.com/v1/air-quality"
        params_air = {
            "latitude": lat, "longitude": lon,
            "hourly": ["carbon_monoxide", "carbon_dioxide", "nitrogen_dioxide", "sulphur_dioxide", "uv_index_clear_sky", "uv_index"],
            "start": start_time, "end": end_time,
        }
        air_responses = openmeteo.weather_api(url_air, params=params_air)
        response_air = air_responses[0]
        hourly_air = response_air.Hourly()
        
        air_data = {
            "carbon_monoxide": hourly_air.Variables(0).ValuesAsNumpy(),
            "carbon_dioxide": hourly_air.Variables(1).ValuesAsNumpy(),
            "nitrogen_dioxide": hourly_air.Variables(2).ValuesAsNumpy(),
            "sulphur_dioxide": hourly_air.Variables(3).ValuesAsNumpy(),
            "uv_index_clear_sky": hourly_air.Variables(4).ValuesAsNumpy(),
            "uv_index": hourly_air.Variables(5).ValuesAsNumpy(),
        }
        air_times = pd.date_range(
            start=pd.to_datetime(hourly_air.Time(), unit="s", utc=True),
            end=pd.to_datetime(hourly_air.TimeEnd(), unit="s", utc=True),
            freq=pd.Timedelta(seconds=hourly_air.Interval()),
            inclusive="left"
        )
        air_df = pd.DataFrame(air_data, index=air_times)

        url_weather = "https://api.open-meteo.com/v1/forecast"
        params_weather = {
            "latitude": lat, "longitude": lon,
            "hourly": ["temperature_2m", "relative_humidity_2m", "precipitation", "windspeed_10m", "winddirection_10m"],
            "start": start_time, "end": end_time,
        }
        weather_responses = openmeteo.weather_api(url_weather, params=params_weather)
        response_weather = weather_responses[0]
        hourly_weather = response_weather.Hourly()
        
        weather_data = {
            "temperature_2m": hourly_weather.Variables(0).ValuesAsNumpy(),
            "relative_humidity_2m": hourly_weather.Variables(1).ValuesAsNumpy(),
            "precipitation": hourly_weather.Variables(2).ValuesAsNumpy(),
            "windspeed_10m": hourly_weather.Variables(3).ValuesAsNumpy(),
            "winddirection_10m": hourly_weather.Variables(4).ValuesAsNumpy(),
        }
        weather_times = pd.date_range(
            start=pd.to_datetime(hourly_weather.Time(), unit="s", utc=True),
            end=pd.to_datetime(hourly_weather.TimeEnd(), unit="s", utc=True),
            freq=pd.Timedelta(seconds=hourly_weather.Interval()),
            inclusive="left"
        )
        weather_df = pd.DataFrame(weather_data, index=weather_times)

        merged_metrics = pd.merge_asof(air_df.sort_index(), weather_df.sort_index(), left_index=True, right_index=True)
        
        target_time = pd.to_datetime(date, utc=True)
        closest_idx = merged_metrics.index.get_indexer([target_time], method='nearest')[0]
        closest_data = merged_metrics.iloc[closest_idx].to_dict()

        # Combine Bus Data + Weather Data
        combined = {**row.to_dict(), **closest_data}
        time.sleep(random.uniform(0.1, 0.3)) 
        return combined
    
    except Exception as e:
        print(f"[Warn] API Error for {lat},{lon}: {e}")
        api_fields = [
            "carbon_monoxide",
            "carbon_dioxide",
            "nitrogen_dioxide",
            "sulphur_dioxide",
            "uv_index_clear_sky",
            "uv_index",
            "temperature_2m",
            "relative_humidity_2m",
            "precipitation",
            "windspeed_10m",
            "winddirection_10m"
        ]
        base = row.to_dict()
        error_combined = {**base, **{field: None for field in api_fields}}
        return error_combined

def process_enrichment(**context):
    sim_date_str = Variable.get("SIMULATION_DATE", default_var=datetime.now().strftime("%Y-%m-%d"))
    input_file = f"s3a://{BUCKET_NAME}/{INPUT_PREFIX}/simulation_{sim_date_str}.csv"
    print(f"Reading input from: {input_file}")

    storage_opts = {
        "key": MINIO_ACCESS_KEY,
        "secret": MINIO_SECRET_KEY,
        "client_kwargs": {"endpoint_url": MINIO_ENDPOINT}
    }

    try:
        df = pd.read_csv(input_file, storage_options=storage_opts)
    except FileNotFoundError:
        print(f"File {input_file} not found. Maybe simulation hasn't run yet.")
        return

    print(f"Processing {len(df)} records...")
    results = []
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {executor.submit(fetch_air_weather, row): idx for idx, row in df.iterrows()}
        
        for future in as_completed(futures):
            res = future.result()
            if res:
                results.append(res)

    if not results:
        print("No data enriched.")
        return

    enriched_df = pd.DataFrame(results)

    output_file = f"s3a://{BUCKET_NAME}/{OUTPUT_PREFIX}/enriched_{sim_date_str}.parquet"
    
    print(f"Writing enriched data to: {output_file}")
    
    enriched_df.to_parquet(
        output_file, 
        index=False,
        storage_options=storage_opts
    )
    print("Enrichment complete!")

with DAG(
    dag_id="bus_enrichment_processing",
    start_date=datetime(2025, 10, 1, tzinfo=local_tz),
    schedule="30 5 * * *",
    catchup=False,
    max_active_runs=1,
    tags=['enrichment', 'iot']
) as dag:

    enrich_task = PythonOperator(
        task_id="fetch_weather_and_save",
        python_callable=process_enrichment,
        outlets=[DATASET_SENSOR_DATA]

    )

    enrich_task