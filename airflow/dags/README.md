# **Giải thích** thư mục

**Cấu trúc thư mục**

```yaml
airflow/dags/
├── BusPositions
│   ├── chieudi.json
│   ├── chieuve.json
│   └── streamed_bus_data.jsonl
├── README.md
├── requirements.txt
└── schedule.py
```

## BusPositions

- `chieudi.json`: file json mô tả chiều đi của xe buýt số 26
- `chieuve.json`: file json mô tả chiều về của xe buýt số 26
- `streamed_bus_data.jsonl`: file jsonl mô phỏng luồng dữ liệu stream

## File `schedule.py`

**Hành vi của file khi chạy**

### 1. Tạo đối tượng DAG ID với các thông số

Khi chạy file `schedule.py`, Apache Airflow sẽ tạo ra một **DAG ID** với các thông số được cấu hình bên trong file. Dưới đây là các thông số được thiết lập trong file này và ý nghĩa của chúng:

```python
with DAG(
    dag_id='bus_stream_simulator',  # Tạo DAG ID
    default_args=default_args,  # Tham số mặc định cho các task
    description='Emit one bus-location point every 30s; regenerate day route at 05:00 Asia/Bangkok',  # Mô tả ngắn về DAG
    schedule=timedelta(seconds=30),  # Lịch chạy DAG mỗi 30 giây
    start_date=pendulum.datetime(2025, 10, 14, 4, 59, tz=VIETNAM_TZ),  # Thời điểm bắt đầu DAG
    catchup=False,  # Không chạy lại các DAG bị bỏ lỡ
    max_active_runs=1,  # Chỉ cho phép một DAG chạy cùng một lúc
    tags=['bus', 'simulator', 'realtime'],  # Thẻ để phân loại DAG
) as dag:
```

#### Thông số DAG

`dag_id = 'bus_stream_simulator'`

- **Giải thích**: Đây là **ID của DAG**. Mỗi DAG trong Airflow cần có một ID duy nhất. Trong trường hợp này, DAG sẽ có tên là `bus_stream_simulator`, dùng để mô phỏng vị trí xe buýt theo thời gian thực.

`default_args = default_args`

- **Giải thích**: Tham số này chứa các thông số mặc định cho DAG, được lấy từ **`default_args`** (một dictionary). Các thông số trong `default_args` giúp cấu hình các đặc tính như chủ sở hữu, retry, và các hành vi mặc định khác cho các task trong DAG.
- Ví dụ: Trong `default_args`, bạn có thể định nghĩa `owner`, `retries`, `depends_on_past`, v.v.

`description = 'Emit one bus-location point every 30s; regenerate day route at 05:00 Asia/Bangkok'`

- **Giải thích**: Mô tả ngắn gọn về DAG này. Ở đây, mô tả nói rằng DAG sẽ phát ra vị trí xe buýt mỗi 30 giây và tái tạo tuyến đường xe buýt vào lúc **5:00 AM** theo múi giờ Việt Nam.

`schedule = timedelta(seconds=30)`

- **Giải thích**: Lịch chạy DAG, được thiết lập là **mỗi 30 giây**. Điều này có nghĩa là **task trong DAG** sẽ được chạy tự động sau mỗi 30 giây. Tham số này sử dụng `timedelta` để chỉ định thời gian.

`start_date = pendulum.datetime(2025, 10, 14, 4, 59, tz=VIETNAM_TZ)`

- **Giải thích**: Thời điểm bắt đầu DAG sẽ được kích hoạt, ở đây là **14/10/2025**, lúc **4:59 AM** theo múi giờ Việt Nam. Đây là thời điểm Airflow bắt đầu chạy DAG này.

`catchup = False`

- **Giải thích**: Khi được đặt là `False`, Airflow sẽ không chạy lại các DAG đã bị bỏ lỡ từ thời điểm `start_date` trở đi. Điều này có nghĩa là DAG sẽ chỉ chạy theo lịch trình từ thời điểm hiện tại mà không quay lại các thời điểm trước đó.

`max_active_runs = 1`

- **Giải thích**: Tham số này chỉ cho phép **một DAG chạy cùng một lúc**. Nếu có nhiều DAG đang chạy, nó sẽ không tạo ra thêm các phiên bản mới của DAG này cho đến khi một phiên bản hiện tại kết thúc.

`tags = ['bus', 'simulator', 'realtime']`

- **Giải thích**: Thẻ này được sử dụng để phân loại DAG, giúp dễ dàng tìm kiếm và lọc các DAG trong giao diện web của Airflow.

### 2. Đối tượng DAG ID sẽ thực hiện các công việc

Khi DAG này được kích hoạt, **đối tượng DAG ID** sẽ thực hiện một hoặc nhiều **công việc (task)**. Dưới đây là các công việc được thực hiện trong file này:

#### Công việc 1: `emit_one_bus_point`

```python
emit_task = PythonOperator(
    task_id='emit_one_bus_point',
    python_callable=emit_one_bus_point,
)
```

- **Giải thích**: Công việc chính trong DAG này là **`emit_one_bus_point`**, được định nghĩa bởi **`PythonOperator`**. Task này gọi hàm Python **`emit_one_bus_point`**, thực hiện các bước sau:
  1. **Đọc dữ liệu tuyến xe buýt chiều đi** từ file `chieudi.json`.
  2. **Tính toán vị trí của xe buýt** dựa trên thời gian thực, sử dụng hàm **`interpolate`** để nội suy giữa các điểm dừng xe buýt.
  3. **Ghi kết quả** vào file `streamed_bus_data.jsonl` dưới dạng **JSONL** (JSON mỗi dòng).
  4. **Kiểm tra nếu tuyến xe đã kết thúc**, nếu không còn điểm dừng nào mới, in thông báo "Đã kết thúc tuyến, không còn điểm mới."

#### Công việc 2: Lịch trình và điều phối (Airflow Scheduler)

```python
schedule=timedelta(seconds=30),  # Lịch chạy DAG mỗi 30 giây
```

- **Giải thích**: DAG này được lên lịch chạy **mỗi 30 giây** theo cấu hình đã định, vì vậy Airflow sẽ tự động kích hoạt công việc **`emit_one_bus_point`** mỗi 30 giây.
- **Lịch trình**:
  - Airflow Scheduler sẽ thực hiện công việc theo lịch trình đã định, giúp bạn **mô phỏng liên tục vị trí xe buýt**.

### Tóm tắt:

1. **Tạo đối tượng DAG ID**:
   - Khi chạy file `schedule.py`, một **DAG ID** với tên là **`bus_stream_simulator`** sẽ được tạo, với các thông số như `start_date`, `schedule`, `max_active_runs`, `catchup`, và `tags`.
2. **Thực hiện các công việc**:

   - **Công việc duy nhất** trong DAG này là **`emit_one_bus_point`**, được thực hiện mỗi 30 giây.
   - Công việc này sẽ:
     1. Đọc dữ liệu tuyến xe buýt từ file `chieudi.json`.
     2. Nội suy vị trí xe buýt theo thời gian thực.
     3. Ghi kết quả vào file `streamed_bus_data.jsonl`.
     4. In ra thông báo nếu tuyến xe đã kết thúc.

   Mỗi lần DAG chạy, các công việc này sẽ tiếp tục được thực hiện theo lịch trình cho đến khi bạn dừng DAG.

## Hướng dẫn chạy file `schedule.py`

```shell
# 1. Tạo môi trường ảo với Conda:
conda create --name airflow_env python=3.11
conda activate airflow_env

# 2. Cài đặt các thư viện cần thiết:
python -m pip install -r requirements.txt

# 3. Khởi tạo cơ sở dữ liệu Airflow:
airflow db init

# 4. Khởi động Airflow Web Server và Scheduler:
airflow webserver --port 8080
airflow scheduler

# 5. Đặt file `schedule.py` vào thư mục `airflow/dags/`.

# 6. Truy cập giao diện web của Airflow: http://localhost:8080
```
