FROM flink:1.20.2-scala_2.12

# ===================== INSTALL PYTHON & PIP =====================
# Cần cài thêm python3-pip để dùng lệnh pip cài thư viện
RUN apt-get update && \
    apt-get install -y python3 python3-pip python3-dev && \
    ln -s /usr/bin/python3 /usr/bin/python && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# ===================== INSTALL PYFLINK LIB =====================
# Quan trọng: Phiên bản PyFlink phải khớp với phiên bản Flink base image (1.20.2)
RUN pip3 install apache-flink==1.20.2

# ===================== CREATE FLINK JAR DIR =====================
RUN mkdir -p /opt/flink/jars

# ===================== COPY FLINK CONNECTOR JARS =====================
COPY flink-connector-jdbc-3.3.0-1.20.jar /opt/flink/jars/
COPY flink-connector-kafka-3.3.0-1.20.jar /opt/flink/jars/
COPY flink-sql-connector-kafka-3.3.0-1.20.jar /opt/flink/jars/
COPY flink-sql-json-1.20.0.jar /opt/flink/jars/
COPY postgresql-42.7.3.jar /opt/flink/jars/

# ===================== COPY JOB =====================
WORKDIR /app
COPY bus_positions_job.py /app/bus_positions_job.py

# ===================== DEFAULT CMD =====================
# Lưu ý: Chạy trực tiếp python như thế này là chế độ "Local" (Standalone)
CMD ["python3", "/app/bus_positions_job.py"]