from pathlib import Path

from pyflink.datastream import StreamExecutionEnvironment
from pyflink.table import EnvironmentSettings, StreamTableEnvironment


def main():
    # 1) Tạo env Flink streaming
    exec_env = StreamExecutionEnvironment.get_execution_environment()
    exec_env.set_parallelism(1)

    settings = (
        EnvironmentSettings.new_instance()
        .in_streaming_mode()
        .build()
    )
    table_env = StreamTableEnvironment.create(exec_env, environment_settings=settings)

    # 2) Đăng ký các JAR connector (Kafka + Debezium JSON)
    # Các file JAR nằm trong thư mục: /flink_libs/
    project_dir = Path(__file__).parent.resolve()
    jar_dir = project_dir / "flink_libs"

    jars = ";".join(
        [
            f"file://{jar_dir / 'flink-sql-connector-kafka-3.3.0-1.20.jar'}",
            f"file://{jar_dir / 'flink-sql-json-1.20.0.jar'}",
            f"file://{jar_dir / 'flink-connector-jdbc-3.3.0-1.20.jar'}",
            f"file://{jar_dir / 'postgresql-42.7.3.jar'}",
        ]
    )

    table_env.get_config().get_configuration().set_string("pipeline.jars", jars)

    # Cho phép dùng một số dynamic options nếu cần
    table_env.get_config().set("table.dynamic-table-options.enabled", "true")

    # 3) Định nghĩa bảng nguồn Kafka dùng Debezium JSON
    source_ddl = """
    CREATE TABLE bus_data_cdc (
        id STRING,
        stop_id STRING,
        stop_name STRING,
        stop_lat DOUBLE,
        stop_lon DOUBLE,
        stop_desc STRING,
        event_time STRING,
        location_name STRING,
        carbon_monoxide DOUBLE,
        carbon_dioxide DOUBLE,
        nitrogen_dioxide DOUBLE,
        sulphur_dioxide DOUBLE,
        uv_index_clear_sky DOUBLE,
        uv_index DOUBLE,
        temperature_2m DOUBLE,
        relative_humidity_2m DOUBLE,
        precipitation DOUBLE,
        windspeed_10m DOUBLE,
        winddirection_10m DOUBLE,
        PRIMARY KEY (id) NOT ENFORCED
    ) WITH (
      'connector' = 'kafka',
      'topic' = 'busdb.public.bus_data',
      'properties.bootstrap.servers' = 'kafka:9092',
      'properties.group.id' = 'pyflink-bus-env-consumer-v2',  
      'scan.startup.mode' = 'earliest-offset',
      'format' = 'debezium-json',
      'debezium-json.schema-include' = 'true',
      'debezium-json.ignore-parse-errors' = 'true'
    )
    """

    table_env.execute_sql(source_ddl)

    # 4) Tạo VIEW tạm bus_scores: tính các score cho từng bản ghi
    scores_view_ddl = """
    CREATE TEMPORARY VIEW bus_scores AS
    SELECT
        PROCTIME() AS proc_time,

        id,
        stop_id,
        stop_name,
        stop_lat,
        stop_lon,
        event_time,
        temperature_2m,
        relative_humidity_2m,
        uv_index,

        -- uv_score: đánh giá mức độ tia UV 0-1
        CASE
          WHEN uv_index IS NULL OR uv_index < 0 THEN 0.0
          WHEN uv_index <= 2 THEN 0.2           -- Low
          WHEN uv_index <= 5 THEN 0.4           -- Moderate
          WHEN uv_index <= 7 THEN 0.7           -- High
          WHEN uv_index <= 10 THEN 0.9          -- Very High
          ELSE 1.0                              -- Extreme (11+)
        END AS uv_score,

        location_name,

        -- raw các chất ô nhiễm
        carbon_monoxide,
        carbon_dioxide,
        nitrogen_dioxide,
        sulphur_dioxide,

        -- air_pollution_score: chuẩn hóa 4 chất về 0-1 rồi lấy trung bình
        (
          (
            CASE
              WHEN carbon_monoxide IS NULL OR carbon_monoxide <= 0 THEN 0.0
              WHEN carbon_monoxide >= 2000 THEN 1.0
              ELSE carbon_monoxide / 2000.0
            END
          )
          +
          (
            CASE
              WHEN carbon_dioxide IS NULL OR carbon_dioxide <= 0 THEN 0.0
              WHEN carbon_dioxide >= 1000 THEN 1.0
              ELSE carbon_dioxide / 1000.0
            END
          )
          +
          (
            CASE
              WHEN nitrogen_dioxide IS NULL OR nitrogen_dioxide <= 0 THEN 0.0
              WHEN nitrogen_dioxide >= 100 THEN 1.0
              ELSE nitrogen_dioxide / 100.0
            END
          )
          +
          (
            CASE
              WHEN sulphur_dioxide IS NULL OR sulphur_dioxide <= 0 THEN 0.0
              WHEN sulphur_dioxide >= 100 THEN 1.0
              ELSE sulphur_dioxide / 100.0
            END
          )
        ) / 4.0 AS air_pollution_score,

        -- heat_score: mức độ "nóng bức / khó chịu"
        CASE
          WHEN temperature_2m IS NULL OR relative_humidity_2m IS NULL THEN 0.5
          WHEN temperature_2m BETWEEN 18 AND 28
               AND relative_humidity_2m BETWEEN 40 AND 70 THEN 0.2  -- dễ chịu
          WHEN temperature_2m < 18 THEN 0.3                          -- hơi lạnh
          WHEN temperature_2m BETWEEN 28 AND 32
               AND relative_humidity_2m <= 70 THEN 0.5              -- hơi nóng
          WHEN temperature_2m BETWEEN 28 AND 32
               AND relative_humidity_2m > 70 THEN 0.7               -- nóng ẩm
          WHEN temperature_2m > 32 AND relative_humidity_2m > 70 THEN 0.9 -- rất nóng ẩm
          ELSE 0.6
        END AS heat_score,

        -- environment_index: tổng hợp 3 trục cho TỪNG BẢN GHI
        (0.5 * (
            (
              (
                CASE
                  WHEN carbon_monoxide IS NULL OR carbon_monoxide <= 0 THEN 0.0
                  WHEN carbon_monoxide >= 2000 THEN 1.0
                  ELSE carbon_monoxide / 2000.0
                END
              )
              +
              (
                CASE
                  WHEN carbon_dioxide IS NULL OR carbon_dioxide <= 0 THEN 0.0
                  WHEN carbon_dioxide >= 1000 THEN 1.0
                  ELSE carbon_dioxide / 1000.0
                END
              )
              +
              (
                CASE
                  WHEN nitrogen_dioxide IS NULL OR nitrogen_dioxide <= 0 THEN 0.0
                  WHEN nitrogen_dioxide >= 100 THEN 1.0
                  ELSE nitrogen_dioxide / 100.0
                END
              )
              +
              (
                CASE
                  WHEN sulphur_dioxide IS NULL OR sulphur_dioxide <= 0 THEN 0.0
                  WHEN sulphur_dioxide >= 100 THEN 1.0
                  ELSE sulphur_dioxide / 100.0
                END
              )
            ) / 4.0
          )
         + 0.2 * (
            CASE
              WHEN uv_index IS NULL OR uv_index < 0 THEN 0.0
              WHEN uv_index <= 2 THEN 0.2
              WHEN uv_index <= 5 THEN 0.4
              WHEN uv_index <= 7 THEN 0.7
              WHEN uv_index <= 10 THEN 0.9
              ELSE 1.0
            END
          )
         + 0.3 * (
            CASE
              WHEN temperature_2m IS NULL OR relative_humidity_2m IS NULL THEN 0.5
              WHEN temperature_2m BETWEEN 18 AND 28
                   AND relative_humidity_2m BETWEEN 40 AND 70 THEN 0.2
              WHEN temperature_2m < 18 THEN 0.3
              WHEN temperature_2m BETWEEN 28 AND 32
                   AND relative_humidity_2m <= 70 THEN 0.5
              WHEN temperature_2m BETWEEN 28 AND 32
                   AND relative_humidity_2m > 70 THEN 0.7
              WHEN temperature_2m > 32 AND relative_humidity_2m > 70 THEN 0.9
              ELSE 0.6
            END
          )
        ) AS environment_index
    FROM bus_data_cdc
    """
    table_env.execute_sql(scores_view_ddl)

    # 5) Tạo bảng sink JDBC trỏ tới Postgres.bus_environment_window
    sink_ddl = """
    CREATE TABLE bus_env_window_sink (
        window_start TIMESTAMP(3),
        window_end   TIMESTAMP(3),

        stop_id        STRING,
        stop_name      STRING,
        location_name  STRING,
        stop_lat       DOUBLE,
        stop_lon       DOUBLE,

        num_events               BIGINT,
        avg_air_pollution_score  DOUBLE,
        avg_uv_score             DOUBLE,
        avg_heat_score           DOUBLE,
        avg_environment_index    DOUBLE
    ) WITH (
      'connector' = 'jdbc',
      'url'        = 'jdbc:postgresql://localhost:5432/busdb?TimeZone=UTC',
      'table-name' = 'bus_environment_window',
      'username'   = 'admin',
      'password'   = 'admin123',
      'driver'     = 'org.postgresql.Driver',
      'sink.buffer-flush.max-rows' = '1',
      'sink.buffer-flush.interval' = '1s',
      'sink.max-retries' = '3'
    )
    """
    table_env.execute_sql(sink_ddl)

    # 6) Viết query window 10s trên VIEW bus_scores, trả ra schema cho map
    query = """
        SELECT
            window_start,
            window_end,

            stop_id,
            stop_name,
            location_name,
            stop_lat,
            stop_lon,

            COUNT(*) AS num_events,

            CAST(AVG(air_pollution_score) AS DOUBLE) AS avg_air_pollution_score,
            CAST(AVG(uv_score)            AS DOUBLE) AS avg_uv_score,
            CAST(AVG(heat_score)          AS DOUBLE) AS avg_heat_score,
            CAST(AVG(environment_index)   AS DOUBLE) AS avg_environment_index
        FROM TABLE(
            TUMBLE(
                TABLE bus_scores,
                DESCRIPTOR(proc_time),
                INTERVAL '10' SECOND
            )
        )
        GROUP BY
            window_start,
            window_end,
            stop_id,
            stop_name,
            location_name,
            stop_lat,
            stop_lon
    """
 
    # 7) INSERT kết quả vào bảng JDBC sink

    insert_sql = "INSERT INTO bus_env_window_sink " + query

    # Submit job Flink
    result = table_env.execute_sql(insert_sql)
    print("Flink job đã được submit, đang chạy streaming...")

    result.wait()


if __name__ == "__main__":
    main()
