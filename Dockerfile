# Dùng Python nhẹ
FROM python:3.11-slim

# Cài một số gói hệ thống cần cho psycopg2 / pandas
RUN apt-get update && apt-get install -y \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Thư mục làm việc trong container
WORKDIR /app

# Copy requirements và cài deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy toàn bộ project vào container (dags, BusPositions, v.v.)
COPY . .

# Lệnh mặc định (có thể override trong docker-compose)
CMD ["python", "dags/stream_demo.py"]
