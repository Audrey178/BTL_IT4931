# from pathlib import Path
# from pyflink.datastream import StreamExecutionEnvironment
# from pyflink.table import EnvironmentSettings, StreamTableEnvironment


# def main():
#     # 1️⃣ Tạo Flink streaming environment
#     exec_env = StreamExecutionEnvironment.get_execution_environment()
#     exec_env.set_parallelism(1)

#     settings = EnvironmentSettings.new_instance().in_streaming_mode().build()
#     t_env = StreamTableEnvironment.create(exec_env, environment_settings=settings)

#     # 2️⃣ Đăng ký JAR connector
#     jar_dir = Path("/mnt/e/20251/BTL_IT4931/k8s/flink").resolve()

#     jars = ";".join([
#         f"file://{jar_dir / 'flink-sql-connector-kafka-3.3.0-1.20.jar'}",
#         f"file://{jar_dir / 'flink-sql-json-1.20.0.jar'}",
#         f"file://{jar_dir / 'flink-connector-jdbc-3.3.0-1.20.jar'}",
#         f"file://{jar_dir / 'postgresql-42.7.3.jar'}",
#     ])

#     t_env.get_config().get_configuration().set_string("pipeline.jars", jars)

#     # 3️⃣ Kafka source table (GIỮ NGUYÊN LOGIC CỦA BẠN)
#     t_env.execute_sql("""
#         CREATE TABLE bus_positions (
#             id STRING,
#             stop_name STRING,
#             stop_lat DOUBLE,
#             stop_lon DOUBLE,
#             stop_desc STRING,
#             event_time STRING,
#             location_name STRING,
#             proc_time AS PROCTIME()
#         ) WITH (
#             'connector' = 'kafka',
#             'topic' = 'datalake.public.bus_positions',
#             'properties.bootstrap.servers' = 'kafka-broker-1:29092',
#             'properties.group.id' = 'flink-debug-group-001',
#             'scan.startup.mode' = 'latest-offset',

#             'format' = 'debezium-json',
#             'debezium-json.schema-include' = 'true',
#             'debezium-json.ignore-parse-errors' = 'true'
#         )
#     """)

#     # 4️⃣ View trung gian (GIỮ NGUYÊN)
#     t_env.execute_sql("""
#         CREATE TEMPORARY VIEW bus_scores AS
#         SELECT
#             proc_time,
#             id,
#             stop_name,
#             stop_lat,
#             stop_lon,
#             stop_desc,
#             event_time,
#             location_name
#         FROM bus_positions
#         WHERE id IS NOT NULL
#     """)

#     # 5️⃣ PostgreSQL sink (TEST INSERT THẬT)
#     t_env.execute_sql("""
#         CREATE TABLE bus_positions_sink (
#             window_start TIMESTAMP(3),
#             window_end TIMESTAMP(3),
#             id STRING,
#             stop_name STRING,
#             stop_lat DOUBLE,
#             stop_lon DOUBLE,
#             stop_desc STRING,
#             event_time STRING,
#             location_name STRING,
#             PRIMARY KEY (id, window_start) NOT ENFORCED
#         ) WITH (
#             'connector' = 'jdbc',
#             'url' = 'jdbc:postgresql://localhost:5432/busdb?TimeZone=UTC',
#             'table-name' = 'bus_positions_window',
#             'username' = 'admin',
#             'password' = 'admin123',
#             'driver' = 'org.postgresql.Driver',
#             'sink.buffer-flush.max-rows' = '1',
#             'sink.buffer-flush.interval' = '1s',
#             'sink.max-retries' = '3'
#         )
#     """)

#     # 6️⃣ Print sink (DEBUG SONG SONG)
#     t_env.execute_sql("""
#         CREATE TABLE print_sink (
#             window_start TIMESTAMP(3),
#             window_end TIMESTAMP(3),
#             id STRING,
#             stop_name STRING,
#             event_time STRING
#         ) WITH (
#             'connector' = 'print'
#         )
#     """)

#     print("🚀 Flink job đang chạy: vừa INSERT Postgres, vừa PRINT ra màn hình")

#     # 7️⃣ INSERT INTO POSTGRES
#     t_env.execute_sql("""
#         INSERT INTO bus_positions_sink
#         SELECT
#             window_start,
#             window_end,
#             id,
#             stop_name,
#             stop_lat,
#             stop_lon,
#             stop_desc,
#             event_time,
#             location_name
#         FROM TABLE(
#             TUMBLE(
#                 TABLE bus_scores,
#                 DESCRIPTOR(proc_time),
#                 INTERVAL '10' SECOND
#             )
#         )
#     """)

#     # 8️⃣ INSERT INTO PRINT (DEBUG)
#     result = t_env.execute_sql("""
#         INSERT INTO print_sink
#         SELECT
#             window_start,
#             window_end,
#             id,
#             stop_name,
#             event_time
#         FROM TABLE(
#             TUMBLE(
#                 TABLE bus_scores,
#                 DESCRIPTOR(proc_time),
#                 INTERVAL '10' SECOND
#             )
#         )
#     """)

#     # Chỉ wait ở job cuối
#     result.wait()


# if __name__ == "__main__":
#     main()
from pathlib import Path
from pyflink.datastream import StreamExecutionEnvironment
from pyflink.table import (
    EnvironmentSettings,
    StreamTableEnvironment,
    DataTypes,
)
from pyflink.table.udf import udf

# ======================================================
# 1️⃣ BUSINESS LOGIC
# ======================================================
class ScoreCalculator:
    @staticmethod
    def get_uv_score(uv_index):
        if uv_index is None or uv_index < 0: return 0.0
        if uv_index <= 2: return 0.2
        elif uv_index <= 5: return 0.4
        elif uv_index <= 7: return 0.7
        elif uv_index <= 10: return 0.9
        return 1.0

    @staticmethod
    def normalize_gas(value, max_threshold):
        if value is None or value <= 0: return 0.0
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
        if temp is None or humidity is None: return 0.5
        if 18 <= temp <= 28 and 40 <= humidity <= 70: return 0.2
        if temp < 18: return 0.3
        if 28 < temp <= 32 and humidity <= 70: return 0.5
        if 28 < temp <= 32 and humidity > 70: return 0.7
        if temp > 32 and humidity > 70: return 0.9
        return 0.6

    @staticmethod
    def get_environment_index(air, uv, heat):
        return 0.5 * air + 0.2 * uv + 0.3 * heat

# ======================================================
# 2️⃣ UDFs
# ======================================================
@udf(input_types=[DataTypes.DOUBLE()], result_type=DataTypes.DOUBLE())
def uv_score(v): return ScoreCalculator.get_uv_score(v)

@udf(input_types=[DataTypes.DOUBLE(), DataTypes.DOUBLE(), DataTypes.DOUBLE(), DataTypes.DOUBLE()], result_type=DataTypes.DOUBLE())
def air_pollution_score(a, b, c, d): return ScoreCalculator.get_air_pollution_score(a, b, c, d)

@udf(input_types=[DataTypes.DOUBLE(), DataTypes.DOUBLE()], result_type=DataTypes.DOUBLE())
def heat_score(t, h): return ScoreCalculator.get_heat_score(t, h)

@udf(input_types=[DataTypes.DOUBLE(), DataTypes.DOUBLE(), DataTypes.DOUBLE()], result_type=DataTypes.DOUBLE())
def environment_index(a, u, h): return ScoreCalculator.get_environment_index(a, u, h)

# ======================================================
# 3️⃣ MAIN JOB
# ======================================================
def main():
    exec_env = StreamExecutionEnvironment.get_execution_environment()
    exec_env.set_parallelism(1)
    settings = EnvironmentSettings.new_instance().in_streaming_mode().build()
    t_env = StreamTableEnvironment.create(exec_env, environment_settings=settings)

    # Config Jars
    jar_dir = Path("/mnt/e/20251/BTL_IT4931/k8s/flink").resolve()
    t_env.get_config().get_configuration().set_string(
        "pipeline.jars",
        ";".join([
            f"file://{jar_dir / 'flink-sql-connector-kafka-3.3.0-1.20.jar'}",
            f"file://{jar_dir / 'flink-sql-json-1.20.0.jar'}",
            f"file://{jar_dir / 'flink-connector-jdbc-3.3.0-1.20.jar'}",
            f"file://{jar_dir / 'postgresql-42.7.3.jar'}",
        ])
    )

    t_env.create_temporary_function("uv_score", uv_score)
    t_env.create_temporary_function("air_pollution_score", air_pollution_score)
    t_env.create_temporary_function("heat_score", heat_score)
    t_env.create_temporary_function("environment_index", environment_index)

    # 1. KAFKA SOURCE (Đã chuẩn hóa theo Schema bạn cung cấp)
    t_env.execute_sql("""
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
            'properties.bootstrap.servers' = 'kafka-broker-1:29092',
            'properties.group.id' = 'flink-production-group',
            'scan.startup.mode' = 'latest-offset',
            'format' = 'debezium-json',
            'debezium-json.schema-include' = 'true',
            'debezium-json.ignore-parse-errors' = 'true'
        )
    """)

    # 2. TRANSFORM VIEW (Đã xử lý time & score)
    t_env.execute_sql("""
        CREATE TEMPORARY VIEW bus_scored AS
        SELECT
            id AS source_id,
            stop_id,
            stop_name,
            stop_lat,
            stop_lon,
            location_name,
            -- Chuyển chuỗi ISO8601 sang TIMESTAMP
            TO_TIMESTAMP(REPLACE(REPLACE(event_time, 'T', ' '), 'Z', '')) AS event_time,
            
            air_pollution_score(carbon_monoxide, carbon_dioxide, nitrogen_dioxide, sulphur_dioxide) AS air_pollution_score,
            uv_score(uv_index) AS uv_score,
            heat_score(temperature_2m, relative_humidity_2m) AS heat_score,
            environment_index(
                air_pollution_score(carbon_monoxide, carbon_dioxide, nitrogen_dioxide, sulphur_dioxide),
                uv_score(uv_index),
                heat_score(temperature_2m, relative_humidity_2m)
            ) AS environment_index
        FROM bus_data_source
        WHERE id IS NOT NULL
    """)

    # 3. JDBC SINK (POSTGRESQL) - Đã cấu hình tối ưu để data vào ngay
    t_env.execute_sql("""
        CREATE TABLE bus_environment_sink (
            source_id STRING,
            stop_id STRING,
            stop_name STRING,
            stop_lat DOUBLE,
            stop_lon DOUBLE,
            location_name STRING,
            event_time TIMESTAMP(3),
            air_pollution_score DOUBLE,
            uv_score DOUBLE,
            heat_score DOUBLE,
            environment_index DOUBLE,
            PRIMARY KEY (source_id) NOT ENFORCED
        ) WITH (
            'connector' = 'jdbc',
            'url' = 'jdbc:postgresql://localhost:5432/busdb', 
            'table-name' = 'bus_environment_result',
            'username' = 'admin',
            'password' = 'admin123',
            'driver' = 'org.postgresql.Driver',
            -- Quan trọng: Đẩy dữ liệu ngay lập tức, không chờ đầy buffer
            'sink.buffer-flush.max-rows' = '1',
            'sink.buffer-flush.interval' = '1s'
        )
    """)

    print("🚀 Flink Job Started: Writing to PostgreSQL...")
    
    # 4. EXECUTE INSERT
    t_env.execute_sql("""
        INSERT INTO bus_environment_sink
        SELECT * FROM bus_scored
    """).wait()

if __name__ == "__main__":
    main()