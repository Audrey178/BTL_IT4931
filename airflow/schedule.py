from datetime import datetime
import json
import os
import uuid
import time
import requests
import pandas as pd
import psycopg2
import numpy as np
import s3fs

# ===================== MINIO / S3 CONFIG =====================
MINIO_ENDPOINT = "https://cuong-dev.cloud:9000"
MINIO_ACCESS_KEY = "minio"
MINIO_SECRET_KEY = "minio123"

BUCKET_NAME = "bus-sensor-data"
FOLDER_PATH = "sensor-data"

# ===================== OUTPUT PATH =====================
DAGS_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_PATH = os.path.join(DAGS_DIR, "BusPositions", "streamed_bus_data.jsonl")

# ===================== POSTGRES CONFIG =====================
HOST = "localhost"
PORT = 5432
DATABASE = "busdb"
USER = "admin"
PASSWORD = "admin123"
CONNECT_TIMEOUT = 5

# ===================== CACHE & UTILS =====================
geocode_cache = {}

def get_pg_connection():
    try:
        conn = psycopg2.connect(
            host=HOST, port=PORT, database=DATABASE, user=USER, password=PASSWORD, connect_timeout=CONNECT_TIMEOUT
        )
        cur = conn.cursor()
        cur.execute("SET TIME ZONE 'Asia/Ho_Chi_Minh';")
        cur.close()
        conn.commit()
        return conn
    except Exception as e:
        print(f"[ERROR] Cannot connect to Postgres: {e}")
        return None

def reverse_geocode(lat, lon):
    key = (round(lat, 6), round(lon, 6))
    if key in geocode_cache: return geocode_cache[key]
    url = f"https://nominatim.openstreetmap.org/reverse?lat={lat}&lon={lon}&format=json"
    try:
        res = requests.get(url, headers={"User-Agent": "bus-stream/1.0"}, timeout=3)
        if res.status_code == 200:
            name = res.json().get("display_name", "Unknown")
            geocode_cache[key] = name
            return name
    except: pass
    return "Unknown location"

def make_json_safe(obj):
    if isinstance(obj, pd.Timestamp): return obj.isoformat()
    if isinstance(obj, (np.integer, np.floating)): return obj.item()
    return obj

def normalize_value(v):
    if v is None: return 0
    if isinstance(v, float) and np.isnan(v): return 0
    return v

def insert_to_postgres(cur, point):
    query = """
        INSERT INTO bus_data (
            id, stop_id, stop_name, stop_lat, stop_lon, stop_desc, event_time, location_name,
            carbon_monoxide, carbon_dioxide, nitrogen_dioxide, sulphur_dioxide,
            uv_index_clear_sky, uv_index, temperature_2m, relative_humidity_2m, precipitation,
            windspeed_10m, winddirection_10m
        ) VALUES (
            %(id)s, %(stop_id)s, %(stop_name)s, %(stop_lat)s, %(stop_lon)s, %(stop_desc)s, %(event_time)s, %(location_name)s,
            %(carbon_monoxide)s, %(carbon_dioxide)s, %(nitrogen_dioxide)s, %(sulphur_dioxide)s,
            %(uv_index_clear_sky)s, %(uv_index)s, %(temperature_2m)s, %(relative_humidity_2m)s, %(precipitation)s,
            %(windspeed_10m)s, %(winddirection_10m)s
        );
    """
    params = {
        "id": str(uuid.uuid4()), "stop_id": point["stopId"], "stop_name": point.get("routeName"),
        "stop_lat": point["stopLat"], "stop_lon": point["stopLon"], "stop_desc": point.get("tags"),
        "event_time": point["datetime"], "location_name": point["location_name"],
        "carbon_monoxide": point["carbon_monoxide"], "carbon_dioxide": point["carbon_dioxide"],
        "nitrogen_dioxide": point["nitrogen_dioxide"], "sulphur_dioxide": point["sulphur_dioxide"],
        "uv_index_clear_sky": point["uv_index_clear_sky"], "uv_index": point["uv_index"],
        "temperature_2m": point["temperature_2m"], "relative_humidity_2m": point["relative_humidity_2m"],
        "precipitation": point["precipitation"], "windspeed_10m": point["windspeed_10m"], "winddirection_10m": point["winddirection_10m"],
    }
    cur.execute(query, params)

# ===================== MAIN STREAMING LOGIC =====================
def stream_realtime_from_minio(delay_seconds=1):
    # 1. Kết nối DB TRƯỚC (để đảm bảo DB sống mới chạy tiếp)
    print(f"[INIT] Checking Database connection...")
    conn = get_pg_connection()
    if not conn:
        print("[FATAL] Không thể kết nối DB. Dừng chương trình.")
        return
    cur = conn.cursor()

    # 2. Kết nối MinIO
    print(f"[INIT] Connecting to MinIO: {MINIO_ENDPOINT}")
    fs = s3fs.S3FileSystem(
        key=MINIO_ACCESS_KEY,
        secret=MINIO_SECRET_KEY,
        endpoint_url=MINIO_ENDPOINT,
        client_kwargs={'verify': False}
    )

    s3_path_pattern = f"{BUCKET_NAME}/{FOLDER_PATH}/*.parquet"
    print(f"[SCAN] Scanning: {s3_path_pattern}")
    
    try:
        files = fs.glob(s3_path_pattern)
        if not files:
            print("[ERROR] Không tìm thấy file parquet nào!")
            return

        # Sắp xếp file để đảm bảo thứ tự thời gian (quan trọng)
        files.sort()
        total_files = len(files)
        print(f"[INFO] Tìm thấy {total_files} file. Bắt đầu xử lý cuốn chiếu (Streaming)...")

        # Tạo file log
        os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
        
        # Mở file log để ghi
        with open(OUTPUT_PATH, "a", encoding="utf-8") as out_f:
            
            # --- VÒNG LẶP LỚN: DUYỆT TỪNG FILE ---
            for i, file_path in enumerate(files):
                print(f"\n>> [FILE {i+1}/{total_files}] Đang tải: {file_path}")
                
                try:
                    # Đọc 1 file vào RAM (nhanh hơn đọc 100 file)
                    df = pd.read_parquet(
                        "s3://" + file_path,
                        storage_options={
                            "key": MINIO_ACCESS_KEY,
                            "secret": MINIO_SECRET_KEY,
                            "client_kwargs": {"endpoint_url": MINIO_ENDPOINT, "verify": False}
                        }
                    )
                    
                    # Sort dữ liệu trong file hiện tại
                    if "datetime" in df.columns:
                        df["datetime"] = pd.to_datetime(df["datetime"])
                        df = df.sort_values("datetime")
                    
                    # --- VÒNG LẶP NHỎ: INSERT TỪNG DÒNG ---
                    for idx, row in df.iterrows():
                        point = {k: normalize_value(make_json_safe(v)) for k, v in row.to_dict().items()}
                        point["location_name"] = reverse_geocode(point["stopLat"], point["stopLon"])

                        # Insert vào Postgres
                        insert_to_postgres(cur, point)
                        conn.commit() # Commit ngay lập tức để dữ liệu hiện lên DB

                        # Ghi log file
                        log_line = json.dumps(point, ensure_ascii=False)
                        out_f.write(log_line + "\n")
                        
                        # In log ra màn hình
                        print(f"   + [INSERT] Bus {point.get('routeName')} | {point['datetime']} | {point['location_name']}")
                        
                        # Delay để giả lập realtime
                        time.sleep(delay_seconds)

                except Exception as e_file:
                    print(f"[WARNING] Lỗi khi xử lý file {file_path}: {e_file}")
                    # Nếu lỗi file này thì bỏ qua, chạy tiếp file sau
                    continue

    except KeyboardInterrupt:
        print("\n[STOP] Người dùng dừng chương trình.")
    except Exception as e:
        print(f"[ERROR] Lỗi hệ thống: {e}")
        import traceback
        traceback.print_exc()
    finally:
        if cur: cur.close()
        if conn: conn.close()
        print("[INFO] Đã đóng kết nối Database.")

if __name__ == "__main__":
    # Delay 1 giây giữa các dòng dữ liệu
    stream_realtime_from_minio(delay_seconds=1)