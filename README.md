# Bus Environment Streaming Demo

Pipeline demo xử lý dữ liệu vị trí xe buýt (Hà Nội): đọc tuyến, nội suy, enrich thời tiết/khí tượng, push vào PostgreSQL; Debezium chuyển thay đổi sang Kafka; consumer đọc Kafka, tính các chỉ số môi trường theo cửa sổ và lưu kết quả vào PostgreSQL khác để phục vụ visualization.

---

## Giới thiệu nhanh

- Mục tiêu: minh họa pipeline streaming end-to-end cho dữ liệu xe buýt, enrich bằng Open-Meteo và tính chỉ số môi trường.
- Thành phần chính:
  - `bus_streamer` (container): `dags/stream_demo.py` — đọc file tuyến, enrich, insert vào `busdb.bus_data`.
  - `debezium_server` (container): capture CDC từ `busdb` → publish Kafka topic `busdb.public.bus_data`.
  - `window_aggregator` (container): `consumer.py` — đọc Kafka, tính scores, aggregate theo tumbling window 10s, insert vào `envdb.bus_environment_window`.

---

## File & container quan trọng

- `docker-compose.yml`: orchestration cho `busdb`, `envdb`, `kafka`, `debezium_server`, `bus_streamer`, `window_aggregator`.
- `Dockerfile`: image cho `bus_streamer` (stream_demo).
- `Dockerfile.consumer`: image cho `window_aggregator` (consumer.py).
- `dags/BusPositions/chieudi.json`: dữ liệu tuyến mẫu.

---

## Hướng dẫn chạy (step-by-step)

Các lệnh dưới đây chạy trên WSL Ubuntu trong thư mục dự án `~/btl_bigdata`.

1. Khởi động infrastructure (DB, Kafka, Debezium, envdb)

```bash
cd ~/btl_bigdata
docker compose up -d busdb envdb kafka debezium_server
docker ps
```

Chờ ~10–20s để Postgres sẵn sàng.

2. Tạo bảng `bus_data` (busdb)

```bash
docker exec -i busdb psql -U admin -d busdb <<'SQL'
CREATE TABLE IF NOT EXISTS bus_data (
    id UUID PRIMARY KEY,
    stop_id UUID NOT NULL,
    stop_name TEXT,
    stop_lat DOUBLE PRECISION,
    stop_lon DOUBLE PRECISION,
    stop_desc TEXT,
    event_time TIMESTAMPTZ,
    location_name TEXT,
    carbon_monoxide DOUBLE PRECISION,
    carbon_dioxide DOUBLE PRECISION,
    nitrogen_dioxide DOUBLE PRECISION,
    sulphur_dioxide DOUBLE PRECISION,
    uv_index_clear_sky DOUBLE PRECISION,
    uv_index DOUBLE PRECISION,
    temperature_2m DOUBLE PRECISION,
    relative_humidity_2m DOUBLE PRECISION,
    precipitation DOUBLE PRECISION,
    windspeed_10m DOUBLE PRECISION,
    winddirection_10m DOUBLE PRECISION
);
SQL
```

3. Tạo bảng `bus_environment_window` (envdb)

```bash
docker exec -i envdb psql -U env_admin -d envdb <<'SQL'
CREATE TABLE IF NOT EXISTS bus_environment_window (
    window_start TIMESTAMPTZ,
    window_end TIMESTAMPTZ,
    stop_id TEXT,
    stop_name TEXT,
    location_name TEXT,
    stop_lat DOUBLE PRECISION,
    stop_lon DOUBLE PRECISION,
    num_events BIGINT,
    avg_air_pollution_score DOUBLE PRECISION,
    avg_uv_score DOUBLE PRECISION,
    avg_heat_score DOUBLE PRECISION,
    avg_environment_index DOUBLE PRECISION
);
SQL
```

4. Chạy `bus_streamer` (ghi dữ liệu vào `busdb`)

```bash
# Chạy foreground để xem logs trực tiếp (thêm -d để chạy nền)
docker compose up bus_streamer

# hoặc chạy nền
# docker compose up -d bus_streamer
```

Mở terminal khác để theo dõi logs:

```bash
docker logs -f bus_streamer
```

5. Kiểm tra dữ liệu đã được insert

```bash
docker exec busdb psql -U admin -d busdb -c "SELECT COUNT(*) FROM bus_data;"
docker exec busdb psql -U admin -d busdb -c "SELECT id, stop_id, stop_name, event_time, location_name FROM bus_data LIMIT 5;"
```

6. Kiểm tra Debezium → Kafka

```bash
docker logs debezium_server | tail -n 50

# Nếu container kafka có script shell
docker exec -it kafka kafka-console-consumer.sh --bootstrap-server localhost:9092 \
  --topic busdb.public.bus_data --from-beginning --max-messages 3
```

7. Chạy `window_aggregator` (consumer)

```bash
# Chạy foreground để debug
docker compose up window_aggregator

# hoặc chạy nền
# docker compose up -d window_aggregator

# Theo dõi logs
docker logs -f window_aggregator
```

8. Kiểm tra kết quả trong `envdb`

```bash
docker exec envdb psql -U env_admin -d envdb -c "SELECT COUNT(*) FROM bus_environment_window;"
docker exec envdb psql -U env_admin -d envdb -c "SELECT * FROM bus_environment_window ORDER BY window_start DESC LIMIT 5;"
```

---

## Lệnh tiện ích

- Dừng toàn bộ containers:

```bash
docker compose down
```

- Dừng và xóa volumes (XÓA DATA):

```bash
docker compose down -v
```

- Rebuild images khi thay đổi code:

```bash
docker compose down
docker compose build --no-cache
docker compose up -d
```

---

## Troubleshooting nhanh

- Nếu `bus_streamer` không ghi dữ liệu: xem `docker logs bus_streamer` — kiểm tra lỗi kết nối DB hoặc lỗi API.
- Nếu Debezium không publish: xem `docker logs debezium_server` — kiểm tra `debezium/conf/application.properties` và `debezium.source.table.include.list`.
- Nếu Kafka topic trống: thử `kafka-console-consumer.sh` trong container `kafka`.
- Nếu `window_aggregator` lỗi khi insert: xem `docker logs window_aggregator` — kiểm tra schema `bus_environment_window` trong `envdb`.

---
