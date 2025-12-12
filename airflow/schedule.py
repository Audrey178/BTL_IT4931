from airflow import DAG
from airflow.providers.standard.operators.python import PythonOperator
from datetime import datetime, timedelta, timezone
import json, uuid, random, requests, os
import numpy as np
import pendulum
import time
import psycopg2

DAGS_DIR = os.path.dirname(__file__)
FORWARD_PATH = os.path.join(DAGS_DIR, 'BusPositions/chieudi.json')
BACKWARD_PATH = os.path.join(DAGS_DIR, 'BusPositions/chieuve.json')
OUTPUT_PATH = os.path.join(DAGS_DIR, 'BusPositions/streamed_bus_data.jsonl')
VIETNAM_TZ = timezone(timedelta(hours=7))
START_TIME = datetime.now(tz=VIETNAM_TZ)

geocode_cache = {}

def random_time(lo, hi):
    return random.randint(lo, hi)

def reverse_geocode(lat, lon, cache):
    key = (round(lat, 6), round(lon, 6))
    if key in cache:
        return cache[key]
    url = f"https://nominatim.openstreetmap.org/reverse?lat={lat}&lon={lon}&format=json"
    headers = {"User-Agent": "bus26A-simulator/1.0"}
    try:
        res = requests.get(url, headers=headers, timeout=5)
        if res.status_code == 200:
            data = res.json()
            name = data.get("display_name", "Unknown location")
            cache[key] = name
            return name
    except Exception as e:
        print(f"[reverse_geocode] error: {e}")
    cache[key] = "Unknown location"
    return "Unknown location"

def interpolate(forward, start_time):
    elapsed = (datetime.now(VIETNAM_TZ) - start_time).total_seconds()

    for i in range(len(forward) - 1):
        t1 = (datetime.fromisoformat(forward[i]["datetime"]) -
              datetime.fromisoformat(forward[0]['datetime'])).total_seconds()
        t2 = (datetime.fromisoformat(forward[i + 1]["datetime"]) -
              datetime.fromisoformat(forward[0]['datetime'])).total_seconds()

        if t1 <= elapsed <= t2:
            ratio = (elapsed - t1) / (t2 - t1)
            lat = forward[i]["stopLat"] + ratio * (forward[i + 1]["stopLat"] - forward[i]["stopLat"])
            lon = forward[i]["stopLon"] + ratio * (forward[i + 1]["stopLon"] - forward[i]["stopLon"])

            return {
                'stopId': str(uuid.uuid4()),
                'stopName': 'random',
                'stopLat': lat,
                'stopLon': lon,
                'stopDesc': '',
                'datetime': datetime.now(VIETNAM_TZ).isoformat(),
                'location_name': reverse_geocode(lat, lon, geocode_cache)
            }
    return None


def insert_to_postgres(point):
    conn = None
    try:
        print("Đang kết nối tới Postgres...")

        conn = psycopg2.connect(
            host="localhost",
            port="5432",
            database="busdb",
            user="admin",
            password="admin123",
            connect_timeout=5 
        )

        cur = conn.cursor()
        query = """
            INSERT INTO bus_positions (
                id, stop_name, stop_lat, stop_lon, stop_desc, event_time, location_name
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s);
        """

        cur.execute(query, (
            point["stopId"],
            point["stopName"],
            point["stopLat"],
            point["stopLon"],
            point["stopDesc"],
            point["datetime"],
            point["location_name"]
        ))

        conn.commit()
        print(f"INSERT thành công ID: {point['stopId']}")
        cur.close()

    except Exception as e:
        print(f"FATAL ERROR Postgres: {e}")
        raise e
    finally:
        if conn:
            conn.close()

def emit_one_bus_point(**context):
    with open(FORWARD_PATH) as f:
        forward = json.load(f)
    point = interpolate(forward, START_TIME)
    
    if point:
        # ghi file .jsonl
        with open(OUTPUT_PATH, "a") as f:
            f.write(json.dumps(point, ensure_ascii=False) + "\n")

        print("Elapsed time: ", point['datetime'])

        # ghi Postgres
        insert_to_postgres(point)
    else:
        print("Đã kết thúc tuyến.")


default_args = {
    'owner': 'vietanh',
    'depends_on_past': False,
    'retries': 0,
}

with DAG(
    dag_id='bus_stream_simulator',
    default_args=default_args,
    description='Emit one bus-location point every 30s AND insert into Postgres for Debezium',
    schedule=timedelta(seconds=30),
    start_date=pendulum.datetime(2025, 10, 14, 4, 59, tz=VIETNAM_TZ),
    catchup=False,
    max_active_runs=1,
    tags=['bus', 'simulator', 'realtime'],
) as dag:
    emit_task = PythonOperator(
        task_id='emit_one_bus_point',
        python_callable=emit_one_bus_point,
    )
    