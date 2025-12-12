CREATE TABLE IF NOT EXISTS bus_environment_window (
    window_start TIMESTAMP,
    window_end   TIMESTAMP,

    stop_id        TEXT,
    stop_name      TEXT,
    location_name  TEXT,
    stop_lat       DOUBLE PRECISION,
    stop_lon       DOUBLE PRECISION,

    num_events               BIGINT,
    avg_air_pollution_score  DOUBLE PRECISION,
    avg_uv_score             DOUBLE PRECISION,
    avg_heat_score           DOUBLE PRECISION,
    avg_environment_index    DOUBLE PRECISION
);
