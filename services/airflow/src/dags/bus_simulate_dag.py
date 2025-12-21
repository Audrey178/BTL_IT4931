from airflow import DAG
from airflow.providers.standard.operators.python import PythonOperator
from airflow.models import Variable
from datetime import datetime, timedelta
import pandas as pd
import math
import random
import os
import uuid
from pendulum import timezone

from utils.config_manager import config_manager

local_tz = timezone("Asia/Ho_Chi_Minh")

MINIO_ENDPOINT = config_manager.storage_config.endpoint
MINIO_ACCESS_KEY = config_manager.storage_config.access_key
MINIO_SECRET_KEY = config_manager.storage_config.secret_key
BUCKET_NAME = config_manager.storage_config.bucket

def haversine(lat1, lon1, lat2, lon2):
    R = 6371000  # meters
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlambda/2)**2
    return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1 - a))

def get_speed_kmh(current_dt):
    hour = current_dt.hour
    if (7 <= hour < 8) or (17 <= hour < 19):
        return random.uniform(20, 40)
    else:
        return random.uniform(45, 60)

def get_simulation_date():
    date_str = Variable.get("SIMULATION_DATE", default_var=datetime.now().strftime("%Y-%m-%d"))
    return datetime.strptime(date_str, "%Y-%m-%d").date()

def run_bus_simulation(**context):
    sim_date = get_simulation_date()
    print(f"=== Running simulation for date: {sim_date} ===")

    current_dir = os.path.dirname(os.path.abspath(__file__))
    input_csv_path = os.path.join(current_dir, "data", "routes_coordinates.csv")
    
    if not os.path.exists(input_csv_path):
        raise FileNotFoundError(f"Cannot find input file at: {input_csv_path}")

    df = pd.read_csv(input_csv_path)
    routes = df['routeName'].unique()
    
    sim_data = []
    start_time = local_tz.datetime(sim_date.year, sim_date.month, sim_date.day, 5, 0, 0)
    end_time   = local_tz.datetime(sim_date.year, sim_date.month, sim_date.day, 21, 0, 0)
    time_step = 30 

    for route in routes:
        current_time = start_time
        route_dir = route 
        stops = df[df['routeName'] == route_dir][['location','lat','lon']].reset_index(drop=True)
        if stops.empty:
            continue

        while current_time < end_time:
            t = current_time
            for i in range(len(stops) - 1):
                if pd.isna(stops.loc[i, 'lat']) or pd.isna(stops.loc[i, 'lon']):
                    # Dữ liệu lỗi/thiếu vẫn tạo record rỗng
                    sim_data.append({
                        "stopId": str(uuid.uuid4()),
                        "countryIso": "",
                        "countryUrl": "",
                        "routeName": route,
                        "stopLat": None,
                        "stopLon": None,
                        "datetime": t.astimezone(local_tz).isoformat(),
                        "tags": {"name": ""}
                    })
                    continue
                
                if pd.isna(stops.loc[i+1, 'lat']) or pd.isna(stops.loc[i+1, 'lon']):
                    continue

                lat1, lon1 = stops.loc[i, ['lat','lon']]
                lat2, lon2 = stops.loc[i+1, ['lat','lon']]
                distance = haversine(lat1, lon1, lat2, lon2)
                
                speed_kmh = get_speed_kmh(t)
                speed_mps = speed_kmh * 1000 / 3600
                total_time = distance / speed_mps if speed_mps > 0 else 30
                steps = max(1, int(total_time // time_step))

                for k in range(steps):
                    ratio = k / steps
                    lat = lat1 + (lat2 - lat1) * ratio
                    lon = lon1 + (lon2 - lon1) * ratio

                    # Thêm nhiễu
                    if random.random() < 0.01: lat = None
                    if random.random() < 0.01: lon = None
                    
                    sim_data.append({
                        "stopId": str(uuid.uuid4()),
                        "countryIso": "VNM",
                        "countryUrl": "vietnam",
                        "routeName": route,
                        "stopLat": lat,
                        "stopLon": lon,
                        "datetime": t.astimezone(local_tz).isoformat(),
                        "tags": {"name": stops.loc[i, "location"]}
                    })
                    t += timedelta(seconds=time_step)
                    if (t >= end_time): break
            current_time = t + timedelta(minutes=10)

    sim_df = pd.DataFrame(sim_data)
    sim_df = sim_df.sort_values(by="datetime").reset_index(drop=True)

    file_name = f"simulation_{sim_date}.csv"
    s3_path = f"s3a://{BUCKET_NAME}/bus-data/{file_name}"
    
    print(f"Uploading to MinIO: {s3_path}")
    
    sim_df.to_csv(
        s3_path, 
        index=False,
        storage_options={
            "key": MINIO_ACCESS_KEY,
            "secret": MINIO_SECRET_KEY,
            "client_kwargs": {
                "endpoint_url": MINIO_ENDPOINT
            }
        }
    )
    print("Upload successfully!")

with DAG(
    dag_id="bus_realtime_simulation_k8s",
    start_date=datetime(2025, 10, 1, tzinfo=local_tz),
    schedule="0 5 * * *", 
    catchup=False,
    max_active_runs=1,
    tags=['simulation', 'python']
) as dag:

    simulate = PythonOperator(
        task_id="simulate_bus_position",
        python_callable=run_bus_simulation,
    )

    simulate 