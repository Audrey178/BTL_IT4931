from pathlib import Path
from pyflink.datastream import StreamExecutionEnvironment
from pyflink.table import (
    EnvironmentSettings,
    StreamTableEnvironment,
    DataTypes,
)
from pyflink.table.udf import udf
import math  
import os

class ScoreCalculator:
    # --- Xử lý địa chỉ: Bỏ 2 đuôi, lấy 2 phần tử sát cuối ---
    @staticmethod
    def extract_location(full_address):
        if not full_address or full_address == "null": 
            return "Unknown"
        
        # Tách chuỗi bằng dấu phẩy
        parts = [p.strip() for p in full_address.split(',')]
        
        # Nếu địa chỉ quá ngắn, trả về nguyên gốc để tránh lỗi index
        if len(parts) < 3:
            return full_address

        remaining_parts = parts[:-2]
        final_parts = remaining_parts[-2:]
        
        # 3. Ghép lại
        return ", ".join(final_parts)

    @staticmethod
    def get_uv_score(uv_index):
        if uv_index is None or math.isnan(uv_index) or uv_index < 0: return 0.0
        if uv_index <= 2: return 0.2
        elif uv_index <= 5: return 0.4
        elif uv_index <= 7: return 0.7
        elif uv_index <= 10: return 0.9
        return 1.0

    @staticmethod
    def normalize_gas(value, max_threshold):
        # Fix lỗi NaN gây chết chương trình
        if value is None or math.isnan(value) or value <= 0: return 0.0
        if value >= max_threshold: return 1.0
        return value / max_threshold

    @staticmethod
    def get_air_pollution_score(co, co2, no2, so2):
        return (
            ScoreCalculator.normalize_gas(co, 2000.0)
            + ScoreCalculator.normalize_gas(co2, 1000.0)
            + ScoreCalculator.normalize_gas(no2, 100.0)
            + ScoreCalculator.normalize_gas(so2, 100.0)
        ) / 4.0

    @staticmethod
    def get_heat_score(temp, humidity):
        if temp is None or math.isnan(temp) or humidity is None or math.isnan(humidity): 
            return 0.5
        if 18 <= temp <= 28 and 40 <= humidity <= 70: return 0.2
        if temp < 18: return 0.3
        if 28 < temp <= 32 and humidity <= 70: return 0.5
        if 28 < temp <= 32 and humidity > 70: return 0.7
        if temp > 32 and humidity > 70: return 0.9
        return 0.6

    @staticmethod
    def calculate_aqi(co, co2, no2, so2):
        score_norm = ScoreCalculator.get_air_pollution_score(co, co2, no2, so2)
        # Fix lỗi NaN khi ép kiểu int
        if score_norm is None or math.isnan(score_norm): return 0
        return int(score_norm * 300)

    @staticmethod
    def get_environment_index(air, uv, heat):
        safe_air = 0.0 if (air is None or math.isnan(air)) else air
        safe_uv = 0.0 if (uv is None or math.isnan(uv)) else uv
        safe_heat = 0.0 if (heat is None or math.isnan(heat)) else heat
        return 0.5 * safe_air + 0.2 * safe_uv + 0.3 * safe_heat

# UDF Definitions
@udf(input_types=[DataTypes.STRING()], result_type=DataTypes.STRING())
def extract_location(addr): 
    return ScoreCalculator.extract_location(addr)

@udf(input_types=[DataTypes.DOUBLE()], result_type=DataTypes.DOUBLE())
def uv_score(v): 
    return ScoreCalculator.get_uv_score(v)

@udf(input_types=[DataTypes.DOUBLE(), DataTypes.DOUBLE(), DataTypes.DOUBLE(), DataTypes.DOUBLE()], result_type=DataTypes.DOUBLE())
def air_pollution_score(a, b, c, d): 
    return ScoreCalculator.get_air_pollution_score(a, b, c, d)

@udf(input_types=[DataTypes.DOUBLE(), DataTypes.DOUBLE()], result_type=DataTypes.DOUBLE())
def heat_score(t, h): 
    return ScoreCalculator.get_heat_score(t, h)

@udf(input_types=[DataTypes.DOUBLE(), DataTypes.DOUBLE(), DataTypes.DOUBLE(), DataTypes.DOUBLE()], result_type=DataTypes.INT())
def calculate_aqi(a, b, c, d): 
    return ScoreCalculator.calculate_aqi(a, b, c, d)

@udf(input_types=[DataTypes.DOUBLE(), DataTypes.DOUBLE(), DataTypes.DOUBLE()], result_type=DataTypes.DOUBLE())
def environment_index(a, u, h): 
    return ScoreCalculator.get_environment_index(a, u, h)

# ======================================================
# 3️⃣ MAIN FLINK JOB
# ======================================================
def main():
    # --- A. Setup Environment ---
    exec_env = StreamExecutionEnvironment.get_execution_environment()
    exec_env.set_parallelism(1)
    settings = EnvironmentSettings.new_instance().in_streaming_mode().build()
    t_env = StreamTableEnvironment.create(exec_env, environment_settings=settings)

    # --- B. Load Jars (K8s version) ---
    # For K8s deployment, jars should be:
    # 1. In the image (ADD to Dockerfile), OR
    # 2. Downloaded from external storage, OR  
    # 3. Use environment variables to specify paths
    jar_dir = os.getenv('JAR_DIR', '/opt/flink/jars')
    
    jar_files = [
        f"file://{jar_dir}/flink-sql-connector-kafka-3.3.0-1.20.jar",
        f"file://{jar_dir}/flink-sql-json-1.20.0.jar",
        f"file://{jar_dir}/flink-connector-jdbc-3.3.0-1.20.jar",
        f"file://{jar_dir}/postgresql-42.7.3.jar",
    ]
    
    # Only set pipeline.jars if files exist
    existing_jars = [j for j in jar_files if os.path.exists(j.replace('file://', ''))]
    if existing_jars:
        t_env.get_config().get_configuration().set_string(
            "pipeline.jars",
            ";".join(existing_jars)
        )
        print(f"✓ Loaded jars: {existing_jars}")
    else:
        print("⚠ No jar files found. They should be pre-configured in Flink cluster.")

    # --- C. Register UDFs in SQL ---
    t_env.create_temporary_function("extract_location", extract_location)
    t_env.create_temporary_function("uv_score", uv_score)
    t_env.create_temporary_function("air_pollution_score", air_pollution_score)
    t_env.create_temporary_function("heat_score", heat_score)
    t_env.create_temporary_function("calculate_aqi", calculate_aqi)
    t_env.create_temporary_function("environment_index", environment_index)

    # --- D. Define Source (Kafka) ---
    # K8s Service: kafka-broker-1:29092 (namespace: batch)
    kafka_broker = os.getenv('KAFKA_BROKER', 'kafka-broker-1:29092')
    
    print(f"📡 Connecting to Kafka: {kafka_broker}")
    
    t_env.execute_sql(f"""
        CREATE TABLE bus_data_source (
            id STRING,
            stop_id STRING,
            stop_name STRING,
            stop_lat DOUBLE,
            stop_lon DOUBLE,
            event_time STRING,
            location_name STRING,
            carbon_monoxide DOUBLE,
            carbon_dioxide DOUBLE,
            nitrogen_dioxide DOUBLE,
            sulphur_dioxide DOUBLE,
            uv_index DOUBLE,
            temperature_2m DOUBLE,
            relative_humidity_2m DOUBLE,
            proc_time AS PROCTIME()
        ) WITH (
            'connector' = 'kafka',
            'topic' = 'datalake.public.bus_data',
            'properties.bootstrap.servers' = '{kafka_broker}',
            'properties.group.id' = 'flink-k8s-production-group', 
            'scan.startup.mode' = 'latest-offset',
            'format' = 'debezium-json',
            'debezium-json.schema-include' = 'true',
            'debezium-json.ignore-parse-errors' = 'true'
        )
    """)

    # --- E. Define Transformation (View) ---
    t_env.execute_sql("""
        CREATE TEMPORARY VIEW bus_scored AS
        SELECT
            id AS source_id,
            stop_id,
            stop_name,
            stop_lat,
            stop_lon,
            
            -- Gọi hàm xử lý địa chỉ mới
            extract_location(location_name) AS location_name,
            
            TO_TIMESTAMP(REPLACE(REPLACE(event_time, 'T', ' '), 'Z', '')) AS event_time,
            
            -- Lấy Nhiệt độ, Độ ẩm trực tiếp
            temperature_2m AS temperature,
            relative_humidity_2m AS humidity,
            
            -- Tính AQI
            calculate_aqi(carbon_monoxide, carbon_dioxide, nitrogen_dioxide, sulphur_dioxide) AS aqi,
            
            -- Tính Index tổng hợp
            environment_index(
                air_pollution_score(carbon_monoxide, carbon_dioxide, nitrogen_dioxide, sulphur_dioxide),
                uv_score(uv_index),
                heat_score(temperature_2m, relative_humidity_2m)
            ) AS environment_index
            
        FROM bus_data_source
        WHERE id IS NOT NULL
    """)

    # --- F. Define Sink (Data Warehouse - PostgreSQL) ---
    # K8s Service: datawarehouse:5432 (for OUTPUT data)
    warehouse_host = os.getenv('WAREHOUSE_HOST', 'datawarehouse')
    warehouse_port = os.getenv('WAREHOUSE_PORT', '5432')
    warehouse_db = os.getenv('WAREHOUSE_DB', 'warehousedb')
    warehouse_user = os.getenv('WAREHOUSE_USER', 'admin')
    warehouse_password = os.getenv('WAREHOUSE_PASSWORD', 'admin123')
    
    print(f"🏭 Data Warehouse: {warehouse_host}:{warehouse_port}/{warehouse_db}")
    
    t_env.execute_sql(f"""
        CREATE TABLE bus_environment_sink (
            source_id STRING,
            stop_id STRING,
            stop_name STRING,
            stop_lat DOUBLE,
            stop_lon DOUBLE,
            location_name STRING,
            event_time TIMESTAMP(3),
            temperature DOUBLE,
            humidity DOUBLE,
            aqi INT,
            environment_index DOUBLE,
            PRIMARY KEY (source_id) NOT ENFORCED
        ) WITH (
            'connector' = 'jdbc',
            'url' = 'jdbc:postgresql://{warehouse_host}:{warehouse_port}/{warehouse_db}', 
            'table-name' = 'bus_environment_result',
            'username' = '{warehouse_user}',
            'password' = '{warehouse_password}',
            'driver' = 'org.postgresql.Driver',
            'sink.buffer-flush.max-rows' = '1',
            'sink.buffer-flush.interval' = '1s'
        )
    """)

    print(" Flink Job Started: Sending Cleaned Location + Temp/Hum/AQI to Postgres...")
    print(f"✓ Kafka topic: datalake.public.bus_data")
    print(f"✓ Output table: bus_environment_result")
    print("=" * 60)
    
    # --- G. Execute ---
    t_env.execute_sql("""
        INSERT INTO bus_environment_sink
        SELECT 
            source_id, stop_id, stop_name, stop_lat, stop_lon, location_name, event_time,
            temperature,
            humidity,
            aqi,
            environment_index
        FROM bus_scored
    """).wait()

if __name__ == "__main__":
    main()