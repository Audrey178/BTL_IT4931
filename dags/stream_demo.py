from datetime import datetime, timedelta, timezone
import json
import os
import uuid
import time

import requests
import pandas as pd
import openmeteo_requests
import requests_cache
from retry_requests import retry
import psycopg2


# =========================
# Cấu hình & hằng số
# =========================

# Thư mục chứa file stream_demo.py
DAGS_DIR = os.path.dirname(os.path.abspath(__file__))

FORWARD_PATH = os.path.join(DAGS_DIR, "BusPositions", "chieudi.json")
BACKWARD_PATH = os.path.join(DAGS_DIR, "BusPositions", "chieuve.json")  # hiện chưa dùng
OUTPUT_PATH = os.path.join(DAGS_DIR, "BusPositions", "streamed_bus_data.jsonl")

VIETNAM_TZ = timezone(timedelta(hours=7))

# Cấu hình Postgres (đọc từ biến môi trường, có giá trị mặc định để chạy trong Docker)
HOST = os.getenv("BUSDB_HOST", "postgres")  # trong docker-compose: service name là 'postgres'
PORT = int(os.getenv("BUSDB_PORT", "5432"))
DATABASE = os.getenv("BUSDB_NAME", "busdb")
USER = os.getenv("BUSDB_USER", "admin")
PASSWORD = os.getenv("BUSDB_PASSWORD", "admin123")
CONNECT_TIMEOUT = 5

# Cache cho reverse geocode để tránh gọi API trùng
geocode_cache = {}


# =========================
# Open-Meteo client (cache + retry)
# =========================

CACHE_DIR = os.path.join(DAGS_DIR, ".cache")
os.makedirs(CACHE_DIR, exist_ok=True)

cache_session = requests_cache.CachedSession(CACHE_DIR, expire_after=3600)
retry_session = retry(cache_session, retries=5, backoff_factor=0.2)
openmeteo = openmeteo_requests.Client(session=retry_session)


# =========================
# Hàm tiện ích
# =========================

def get_pg_connection():
    """Tạo và trả về kết nối PostgreSQL."""
    return psycopg2.connect(
        host=HOST,
        port=PORT,
        database=DATABASE,
        user=USER,
        password=PASSWORD,
        connect_timeout=CONNECT_TIMEOUT,
    )


def reverse_geocode(lat, lon, cache):
    """
    Chuyển đổi tọa độ (lat, lon) thành tên địa điểm (địa chỉ dạng text)
    bằng API Nominatim của OpenStreetMap. Có dùng cache đơn giản.
    """
    key = (round(lat, 6), round(lon, 6))
    if key in cache:
        return cache[key]

    url = f"https://nominatim.openstreetmap.org/reverse?lat={lat}&lon={lon}&format=json"
    headers = {"User-Agent": "bus-simulator/1.0"}

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
    """
    (Hiện CHƯA dùng trong hàm chính, giữ lại để sau này mô phỏng realtime.)

    Nội suy vị trí hiện tại của xe trên tuyến forward, trả về 1 điểm giữa đường.

    forward: list các điểm trong chieudi.json
    start_time: thời điểm bắt đầu mô phỏng (datetime)
    """
    elapsed = (datetime.now(VIETNAM_TZ) - start_time).total_seconds()

    for i in range(len(forward) - 1):
        t1 = (
            datetime.fromisoformat(forward[i]["datetime"])
            - datetime.fromisoformat(forward[0]["datetime"])
        ).total_seconds()
        t2 = (
            datetime.fromisoformat(forward[i + 1]["datetime"])
            - datetime.fromisoformat(forward[0]["datetime"])
        ).total_seconds()

        if t1 <= elapsed <= t2 and t2 > t1:
            ratio = (elapsed - t1) / (t2 - t1)
            lat = forward[i]["stopLat"] + ratio * (
                forward[i + 1]["stopLat"] - forward[i]["stopLat"]
            )
            lon = forward[i]["stopLon"] + ratio * (
                forward[i + 1]["stopLon"] - forward[i]["stopLon"]
            )

            return {
                "stopId": str(uuid.uuid4()),
                "stopName": "random",
                "stopLat": lat,
                "stopLon": lon,
                "stopDesc": "",
                "datetime": datetime.now(VIETNAM_TZ).isoformat(),
            }

    return None


def enrich_point(point):
    """
    Làm giàu dữ liệu cho 1 điểm bus:
      - Gắn location_name (reverse geocode).
      - Gắn dữ liệu thời tiết & chất lượng không khí từ Open-Meteo.

    Trả về: dict point đã enrich (thêm nhiều field).
    """
    lat = point["stopLat"]
    lon = point["stopLon"]
    date_str = point["datetime"]

    # Bắt đầu từ bản copy để không mutate object gốc
    enriched = dict(point)

    # 1) Enrich tên địa điểm
    enriched["location_name"] = reverse_geocode(lat, lon, geocode_cache)

    try:
        # Chuyển sang UTC để call Open-Meteo
        dt_utc = pd.to_datetime(date_str, utc=True)
        start_time = (dt_utc - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M")
        end_time = (dt_utc + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M")

        # --------- API: air-quality ----------
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
                "uv_index",
            ],
            "start": start_time,
            "end": end_time,
        }
        air_responses = openmeteo.weather_api(air_url, params=air_params)
        air_response = air_responses[0]
        air_hourly = air_response.Hourly()

        air_times = pd.date_range(
            start=pd.to_datetime(air_hourly.Time(), unit="s", utc=True),
            end=pd.to_datetime(air_hourly.TimeEnd(), unit="s", utc=True),
            freq=pd.Timedelta(seconds=air_hourly.Interval()),
            inclusive="left",
        )

        air_df = pd.DataFrame(
            {
                "datetime_utc": air_times,
                "carbon_monoxide": air_hourly.Variables(0).ValuesAsNumpy(),
                "carbon_dioxide": air_hourly.Variables(1).ValuesAsNumpy(),
                "nitrogen_dioxide": air_hourly.Variables(2).ValuesAsNumpy(),
                "sulphur_dioxide": air_hourly.Variables(3).ValuesAsNumpy(),
                "uv_index_clear_sky": air_hourly.Variables(4).ValuesAsNumpy(),
                "uv_index": air_hourly.Variables(5).ValuesAsNumpy(),
            }
        )

        # --------- API: weather ----------
        weather_url = "https://api.open-meteo.com/v1/forecast"
        weather_params = {
            "latitude": lat,
            "longitude": lon,
            "hourly": [
                "temperature_2m",
                "relative_humidity_2m",
                "precipitation",
                "windspeed_10m",
                "winddirection_10m",
            ],
            "start": start_time,
            "end": end_time,
        }
        weather_responses = openmeteo.weather_api(weather_url, params=weather_params)
        weather_response = weather_responses[0]
        weather_hourly = weather_response.Hourly()

        weather_times = pd.date_range(
            start=pd.to_datetime(weather_hourly.Time(), unit="s", utc=True),
            end=pd.to_datetime(weather_hourly.TimeEnd(), unit="s", utc=True),
            freq=pd.Timedelta(seconds=weather_hourly.Interval()),
            inclusive="left",
        )

        weather_df = pd.DataFrame(
            {
                "datetime_utc": weather_times,
                "temperature_2m": weather_hourly.Variables(0).ValuesAsNumpy(),
                "relative_humidity_2m": weather_hourly.Variables(1).ValuesAsNumpy(),
                "precipitation": weather_hourly.Variables(2).ValuesAsNumpy(),
                "windspeed_10m": weather_hourly.Variables(3).ValuesAsNumpy(),
                "winddirection_10m": weather_hourly.Variables(4).ValuesAsNumpy(),
            }
        )

        # Merge 2 nguồn theo thời gian gần nhất
        merged_df = pd.merge_asof(
            air_df.sort_values("datetime_utc"),
            weather_df.sort_values("datetime_utc"),
            on="datetime_utc",
        )

        target_time = dt_utc
        idx = (merged_df["datetime_utc"] - target_time).abs().argmin()
        closest_row = merged_df.iloc[int(idx)]

        weather_fields = closest_row.drop(labels=["datetime_utc"]).to_dict()
        enriched.update(weather_fields)

    except Exception as e:
        print(f"[enrich_point] Weather enrich error for point {point.get('stopId')}: {e}")

    return enriched


def insert_point(cur, point):
    """
    Insert một điểm enrich vào bảng bus_data.
    - id: event_id (UUID mới mỗi lần)
    - stop_id: stopId từ JSON (mã điểm dừng)
    """
    event_id = str(uuid.uuid4())

    query = """
        INSERT INTO bus_data (
            id,
            stop_id,
            stop_name,
            stop_lat,
            stop_lon,
            stop_desc,
            event_time,
            location_name,
            carbon_monoxide,
            carbon_dioxide,
            nitrogen_dioxide,
            sulphur_dioxide,
            uv_index_clear_sky,
            uv_index,
            temperature_2m,
            relative_humidity_2m,
            precipitation,
            windspeed_10m,
            winddirection_10m
        )
        VALUES (
            %(id)s,
            %(stop_id)s,
            %(stopName)s,
            %(stopLat)s,
            %(stopLon)s,
            %(stopDesc)s,
            %(datetime)s,
            %(location_name)s,
            %(carbon_monoxide)s,
            %(carbon_dioxide)s,
            %(nitrogen_dioxide)s,
            %(sulphur_dioxide)s,
            %(uv_index_clear_sky)s,
            %(uv_index)s,
            %(temperature_2m)s,
            %(relative_humidity_2m)s,
            %(precipitation)s,
            %(windspeed_10m)s,
            %(winddirection_10m)s
        );
    """

    db_params = dict(point)  # copy từ enriched_point
    db_params["id"] = event_id
    db_params["stop_id"] = point.get("stopId")

    cur.execute(query, db_params)


def stream_forward_realtime(delay_seconds=10, max_points=None):
    """
    Mô phỏng realtime:
      - Đọc tuyến chieudi.json
      - Mỗi lần gửi 1 điểm:
          + enrich
          + log ra màn hình
          + ghi file JSONL
          + insert vào PostgreSQL
      - Nghỉ delay_seconds giữa các điểm.
    """
    print("=== Stream tuyến chiều đi (chieudi.json) theo dạng realtime ===")
    print(f"Đọc tuyến từ: {FORWARD_PATH}")
    print(f"Delay giữa các điểm: {delay_seconds} giây")

    # 1) Đọc tuyến
    with open(FORWARD_PATH, "r", encoding="utf-8") as f:
        forward = json.load(f)

    total_points = len(forward)
    if max_points is not None:
        total_points = min(total_points, max_points)

    print(f"Tổng số điểm sẽ stream: {total_points}")

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)

    conn = None
    try:
        conn = get_pg_connection()
        cur = conn.cursor()
        print("Đã kết nối tới PostgreSQL.")

        with open(OUTPUT_PATH, "a", encoding="utf-8") as out_f:
            for idx, raw_point in enumerate(forward, start=1):
                if idx > total_points:
                    break

                point = dict(raw_point)

                # Bảo đảm có stopId và datetime
                if "stopId" not in point:
                    point["stopId"] = str(uuid.uuid4())

                if "datetime" not in point:
                    point["datetime"] = datetime.now(VIETNAM_TZ).isoformat()

                # Enrich dữ liệu
                enriched_point = enrich_point(point)

                # Log ra màn hình (gọn hơn chút cho realtime)
                print(f"\n===== Điểm {idx}/{total_points} =====")
                print(
                    json.dumps(
                        {
                            "stopId": enriched_point.get("stopId"),
                            "stopName": enriched_point.get("stopName"),
                            "event_time": enriched_point.get("datetime"),
                            "location_name": enriched_point.get("location_name"),
                            "temperature_2m": enriched_point.get("temperature_2m"),
                            "uv_index": enriched_point.get("uv_index"),
                        },
                        ensure_ascii=False,
                        indent=2,
                    )
                )

                # Ghi file JSONL đầy đủ
                out_f.write(json.dumps(enriched_point, ensure_ascii=False) + "\n")

                # Ghi DB
                insert_point(cur, enriched_point)
                conn.commit()

                # Nếu chưa phải điểm cuối thì ngủ
                if idx < total_points:
                    print(f"Đợi {delay_seconds} giây trước khi gửi điểm tiếp theo...")
                    time.sleep(delay_seconds)

        print(f"\nĐã stream xong {total_points} điểm.")
        cur.close()
    except Exception as e:
        print(f"ERROR khi stream realtime: {e}")
        if conn:
            conn.rollback()
    finally:
        if conn:
            conn.close()

# =========================
# Entry point
# =========================

if __name__ == "__main__":
    stream_forward_realtime(delay_seconds=1, max_points=None)
