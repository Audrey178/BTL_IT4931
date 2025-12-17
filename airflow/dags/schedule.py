from datetime import datetime, timedelta, timezone
import json
import os
import uuid
import time

import requests
import pandas as pd
import psycopg2

import openmeteo_requests
import requests_cache
from retry_requests import retry


# ===================== PATH & TIMEZONE =====================
DAGS_DIR = os.path.dirname(os.path.abspath(__file__))

FORWARD_PATH = os.path.join(DAGS_DIR, "BusPositions", "chieudi.json")
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

CACHE_DIR = os.path.join(DAGS_DIR, ".cache")
os.makedirs(CACHE_DIR, exist_ok=True)

cache_session = requests_cache.CachedSession(CACHE_DIR, expire_after=3600)
retry_session = retry(cache_session, retries=5, backoff_factor=0.2)
openmeteo = openmeteo_requests.Client(session=retry_session)


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


# ===================== ENRICH =====================
def enrich_point(point):
    enriched = dict(point)

    lat = point["stopLat"]
    lon = point["stopLon"]

    enriched["location_name"] = reverse_geocode(lat, lon)

    try:
        dt_utc = pd.to_datetime(point["datetime"], utc=True)
        start = (dt_utc - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M")
        end   = (dt_utc + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M")

        # ---- AIR QUALITY ----
        air_url = "https://air-quality-api.open-meteo.com/v1/air-quality"
        air_params = {
            "latitude": lat,
            "longitude": lon,
            "hourly": [
                "carbon_monoxide",
                "carbon_dioxide",
                "nitrogen_dioxide",
                "sulphur_dioxide",
                "uv_index_clear_sky",
                "uv_index"
            ],
            "start": start,
            "end": end
        }

        air = openmeteo.weather_api(air_url, params=air_params)[0].Hourly()

        air_df = pd.DataFrame({
            "datetime_utc": pd.date_range(
                start=pd.to_datetime(air.Time(), unit="s", utc=True),
                end=pd.to_datetime(air.TimeEnd(), unit="s", utc=True),
                freq=pd.Timedelta(seconds=air.Interval()),
                inclusive="left"
            ),
            "carbon_monoxide": air.Variables(0).ValuesAsNumpy(),
            "carbon_dioxide": air.Variables(1).ValuesAsNumpy(),
            "nitrogen_dioxide": air.Variables(2).ValuesAsNumpy(),
            "sulphur_dioxide": air.Variables(3).ValuesAsNumpy(),
            "uv_index_clear_sky": air.Variables(4).ValuesAsNumpy(),
            "uv_index": air.Variables(5).ValuesAsNumpy(),
        })

        # ---- WEATHER ----
        weather_url = "https://api.open-meteo.com/v1/forecast"
        weather_params = {
            "latitude": lat,
            "longitude": lon,
            "hourly": [
                "temperature_2m",
                "relative_humidity_2m",
                "precipitation",
                "windspeed_10m",
                "winddirection_10m"
            ],
            "start": start,
            "end": end
        }

        w = openmeteo.weather_api(weather_url, params=weather_params)[0].Hourly()

        weather_df = pd.DataFrame({
            "datetime_utc": pd.date_range(
                start=pd.to_datetime(w.Time(), unit="s", utc=True),
                end=pd.to_datetime(w.TimeEnd(), unit="s", utc=True),
                freq=pd.Timedelta(seconds=w.Interval()),
                inclusive="left"
            ),
            "temperature_2m": w.Variables(0).ValuesAsNumpy(),
            "relative_humidity_2m": w.Variables(1).ValuesAsNumpy(),
            "precipitation": w.Variables(2).ValuesAsNumpy(),
            "windspeed_10m": w.Variables(3).ValuesAsNumpy(),
            "winddirection_10m": w.Variables(4).ValuesAsNumpy(),
        })

        merged = pd.merge_asof(
            air_df.sort_values("datetime_utc"),
            weather_df.sort_values("datetime_utc"),
            on="datetime_utc"
        )

        row = merged.iloc[(merged["datetime_utc"] - dt_utc).abs().argmin()]
        enriched.update(row.drop("datetime_utc").to_dict())

    except Exception as e:
        print("[enrich_point] error:", e)

    return enriched


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
            %(id)s, %(stop_id)s, %(stopName)s, %(stopLat)s, %(stopLon)s, %(stopDesc)s,
            %(datetime)s, %(location_name)s,
            %(carbon_monoxide)s, %(carbon_dioxide)s, %(nitrogen_dioxide)s, %(sulphur_dioxide)s,
            %(uv_index_clear_sky)s, %(uv_index)s,
            %(temperature_2m)s, %(relative_humidity_2m)s, %(precipitation)s,
            %(windspeed_10m)s, %(winddirection_10m)s
        );
    """

    params = dict(point)
    params["id"] = str(uuid.uuid4())
    params["stop_id"] = point["stopId"]

    cur.execute(query, params)


# ===================== STREAM =====================
def stream_realtime(delay_seconds=1):
    with open(FORWARD_PATH, "r", encoding="utf-8") as f:
        forward = json.load(f)

    conn = get_pg_connection()
    cur = conn.cursor()

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)

    with open(OUTPUT_PATH, "a", encoding="utf-8") as out_f:
        for idx, raw in enumerate(forward, start=1):
            point = dict(raw)
            point.setdefault("stopId", str(uuid.uuid4()))
            point.setdefault("datetime", datetime.now(VIETNAM_TZ).isoformat())

            enriched = enrich_point(point)

            insert_to_postgres(cur, enriched)
            conn.commit()

            out_f.write(json.dumps(enriched, ensure_ascii=False) + "\n")

            print(f"[{idx}] {enriched['location_name']} | {enriched['temperature_2m']}°C")

            time.sleep(delay_seconds)

    cur.close()
    conn.close()


# ===================== MAIN =====================
if __name__ == "__main__":
    stream_realtime(delay_seconds=1)
