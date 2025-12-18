from datetime import datetime, timedelta, timezone
import json
import os
import uuid
import time
import requests
import pandas as pd
import psycopg2
import numpy as np

# ===================== PATH & TIMEZONE =====================
DAGS_DIR = os.path.dirname(os.path.abspath(__file__))

PARQUET_PATH = os.path.join(DAGS_DIR, "BusPositions", "bus_stream.parquet")
OUTPUT_PATH  = os.path.join(DAGS_DIR, "BusPositions", "streamed_bus_data.jsonl")

VIETNAM_TZ = timezone(timedelta(hours=7))

# ===================== POSTGRES CONFIG =====================
HOST = "localhost"
PORT = 5432
DATABASE = "busdb"
USER = "admin"
PASSWORD = "admin123"
CONNECT_TIMEOUT = 5

# ===================== CACHE =====================
geocode_cache = {}

# ===================== POSTGRES =====================
def get_pg_connection():
    return psycopg2.connect(
        host=HOST,
        port=PORT,
        database=DATABASE,
        user=USER,
        password=PASSWORD,
        connect_timeout=CONNECT_TIMEOUT
    )

# ===================== GEO =====================
def reverse_geocode(lat, lon):
    key = (round(lat, 6), round(lon, 6))
    if key in geocode_cache:
        return geocode_cache[key]

    url = f"https://nominatim.openstreetmap.org/reverse?lat={lat}&lon={lon}&format=json"
    headers = {"User-Agent": "bus-stream-simulator/1.0"}

    try:
        res = requests.get(url, headers=headers, timeout=5)
        if res.status_code == 200:
            name = res.json().get("display_name", "Unknown location")
            geocode_cache[key] = name
            return name
    except Exception as e:
        print("[reverse_geocode] error:", e)

    geocode_cache[key] = "Unknown location"
    return "Unknown location"

# ===================== JSON SAFE =====================
def make_json_safe(obj):
    if isinstance(obj, pd.Timestamp):
        return obj.isoformat()
    if isinstance(obj, (np.integer, np.floating)):
        return obj.item()
    return obj

# ===================== NORMALIZE NULL / NaN =====================
def normalize_value(v):
    if v is None:
        return 0
    if isinstance(v, float) and np.isnan(v):
        return 0
    return v

# ===================== INSERT =====================
def insert_to_postgres(cur, point):
    query = """
        INSERT INTO bus_data (
            id, stop_id, stop_name, stop_lat, stop_lon, stop_desc,
            event_time, location_name,
            carbon_monoxide, carbon_dioxide, nitrogen_dioxide, sulphur_dioxide,
            uv_index_clear_sky, uv_index,
            temperature_2m, relative_humidity_2m, precipitation,
            windspeed_10m, winddirection_10m
        )
        VALUES (
            %(id)s, %(stop_id)s, %(stop_name)s, %(stop_lat)s, %(stop_lon)s, %(stop_desc)s,
            %(event_time)s, %(location_name)s,
            %(carbon_monoxide)s, %(carbon_dioxide)s, %(nitrogen_dioxide)s, %(sulphur_dioxide)s,
            %(uv_index_clear_sky)s, %(uv_index)s,
            %(temperature_2m)s, %(relative_humidity_2m)s, %(precipitation)s,
            %(windspeed_10m)s, %(winddirection_10m)s
        );
    """

    params = {
        "id": str(uuid.uuid4()),
        "stop_id": point["stopId"],
        "stop_name": point.get("routeName"),
        "stop_lat": point["stopLat"],
        "stop_lon": point["stopLon"],
        "stop_desc": point.get("tags"),
        "event_time": point["datetime"],
        "location_name": point["location_name"],

        "carbon_monoxide": point["carbon_monoxide"],
        "carbon_dioxide": point["carbon_dioxide"],
        "nitrogen_dioxide": point["nitrogen_dioxide"],
        "sulphur_dioxide": point["sulphur_dioxide"],

        "uv_index_clear_sky": point["uv_index_clear_sky"],
        "uv_index": point["uv_index"],

        "temperature_2m": point["temperature_2m"],
        "relative_humidity_2m": point["relative_humidity_2m"],
        "precipitation": point["precipitation"],

        "windspeed_10m": point["windspeed_10m"],
        "winddirection_10m": point["winddirection_10m"],
    }

    cur.execute(query, params)

# ===================== STREAM FROM PARQUET =====================
def stream_realtime_from_parquet(delay_seconds=1):
    print("[INFO] Loading parquet:", PARQUET_PATH)

    df = pd.read_parquet(PARQUET_PATH)

    # Parse & sort theo event time
    df["datetime"] = pd.to_datetime(df["datetime"])
    df = df.sort_values("datetime")

    conn = get_pg_connection()
    cur = conn.cursor()

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)

    with open(OUTPUT_PATH, "a", encoding="utf-8") as out_f:
        for idx, row in df.iterrows():

            # Convert row -> dict + JSON safe + NULL/NaN -> 0
            point = {
                k: normalize_value(make_json_safe(v))
                for k, v in row.to_dict().items()
            }

            # Reverse geocode
            point["location_name"] = reverse_geocode(
                point["stopLat"], point["stopLon"]
            )

            # Insert Postgres
            insert_to_postgres(cur, point)
            conn.commit()

            # Write JSONL
            out_f.write(json.dumps(point, ensure_ascii=False) + "\n")

            print(
                f"[{idx}] {point.get('routeName')} | "
                f"{point['temperature_2m']:.1f}°C | "
                f"{point['datetime']}"
            )

            time.sleep(delay_seconds)

    cur.close()
    conn.close()

# ===================== MAIN =====================
if __name__ == "__main__":
    stream_realtime_from_parquet(delay_seconds=1)
