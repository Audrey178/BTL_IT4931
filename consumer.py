"""
Kafka Consumer with Environment Index Calculation
- Xử lý Debezium JSON từ busdb.public.bus_data
- Tính scores: uv_score, air_pollution_score, heat_score, environment_index
- Tumbling window 10 giây (processing time) + aggregation
- Ghi kết quả vào PostgreSQL (envdb.bus_environment_window)
"""

import sys
import json
import time
import os
import psycopg2
from kafka import KafkaConsumer
from datetime import datetime
from collections import defaultdict
from psycopg2.extras import execute_values


class PostgreSQLWriter:
    """Ghi window aggregation results vào PostgreSQL"""
    
    def __init__(self, host=None, port=None, database=None, 
                 user=None, password=None):
        # Get from environment or use defaults
        self.host =     host or os.getenv('DB_HOST', 'localhost')
        self.user =     user or os.getenv('DB_USER', 'env_admin')
        self.port = int(port or os.getenv('DB_PORT', '5433'))
        self.database = database or os.getenv('DB_NAME', 'envdb')
        self.password = password or os.getenv('DB_PASSWORD', 'env_admin123')
        self.conn = None
        self.connect()
    
    def connect(self):
        """Kết nối tới PostgreSQL"""
        try:
            self.conn = psycopg2.connect(
                host=self.host,
                port=self.port,
                database=self.database,
                user=self.user,
                password=self.password
            )
            print(f"  ✓ Connected to PostgreSQL ({self.host}:{self.port}/{self.database})", flush=True)
        except Exception as e:
            print(f"  ✗ Failed to connect PostgreSQL: {e}", flush=True)
            raise
    
    def insert_window_result(self, window_result):
        """Ghi một window result vào database"""
        try:
            cursor = self.conn.cursor()
            
            insert_sql = """
                INSERT INTO bus_environment_window (
                    window_start, 
                    window_end, 
                    stop_id, 
                    stop_name, 
                    location_name,
                    stop_lat, 
                    stop_lon, 
                    num_events, 
                    avg_air_pollution_score,
                    avg_uv_score, 
                    avg_heat_score, 
                    avg_environment_index
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """
            
            cursor.execute(insert_sql, (
                window_result['window_start'],
                window_result['window_end'],
                window_result['stop_id'],
                window_result['stop_name'],
                window_result['location_name'],
                window_result['stop_lat'],
                window_result['stop_lon'],
                window_result['num_events'],
                window_result['avg_air_pollution_score'],
                window_result['avg_uv_score'],
                window_result['avg_heat_score'],
                window_result['avg_environment_index']
            ))
            
            self.conn.commit()
        except Exception as e:
            print(f"  ✗ Error inserting window result: {e}", flush=True)
            self.conn.rollback()
    
    def close(self):
        """Đóng kết nối"""
        if self.conn:
            self.conn.close()
            print("  ✓ PostgreSQL connection closed", flush=True)


class ScoreCalculator:
    """Tính toán scores cho environment index"""
    
    @staticmethod
    def get_uv_score(uv_index):
        """Tính UV score từ UV index (0-1)"""
        if uv_index is None or uv_index < 0:
            return 0.0
        if uv_index <= 2:
            return 0.2
        elif uv_index <= 5:
            return 0.4
        elif uv_index <= 7:
            return 0.7
        elif uv_index <= 10:
            return 0.9
        else:
            return 1.0
    
    @staticmethod
    def normalize_gas(value, max_threshold):
        """Chuẩn hóa giá trị khí thành 0-1"""
        if value is None or value <= 0:
            return 0.0
        if value >= max_threshold:
            return 1.0
        return value / max_threshold
    
    @staticmethod
    def get_air_pollution_score(co, co2, no2, so2):
        """Tính air pollution score từ 4 chất khí (0-1)"""
        co_score  = ScoreCalculator.normalize_gas(co,  2000.0)
        co2_score = ScoreCalculator.normalize_gas(co2, 1000.0)
        no2_score = ScoreCalculator.normalize_gas(no2, 100.0)
        so2_score = ScoreCalculator.normalize_gas(so2, 100.0)
        
        return (co_score + co2_score + no2_score + so2_score) / 4.0
    
    @staticmethod
    def get_heat_score(temp, humidity):
        """Tính heat score từ nhiệt độ và độ ẩm (0-1)"""
        if temp is None or humidity is None:
            return 0.5
        
        # 18-28°C và 40-70% humidity → 0.2 (thoải mái)
        if 18 <= temp <= 28 and 40 <= humidity <= 70:
            return 0.2
        
        # < 18°C → 0.3 (hơi lạnh)
        if temp < 18:
            return 0.3
        
        # 28-32°C và <=70% → 0.5 (hơi nóng nhưng khô)
        if 28 < temp <= 32 and humidity <= 70:
            return 0.5
        
        # 28-32°C và >70% → 0.7 (nóng ẩm)
        if 28 < temp <= 32 and humidity > 70:
            return 0.7
        
        # >32°C và >70% → 0.9 (rất nóng ẩm)
        if temp > 32 and humidity > 70:
            return 0.9
        
        # Các trường hợp còn lại
        return 0.6
    
    @staticmethod
    def get_environment_index(air_pollution_score, uv_score, heat_score):
        """Tính environment index tổng hợp (0-1)"""
        return 0.5 * air_pollution_score + 0.2 * uv_score + 0.3 * heat_score


class DebeziumMessageProcessor:
    """Parse Debezium JSON và tính scores"""
    
    def __init__(self):
        self.record_count = 0
    
    def process(self, message_bytes):
        """Xử lý một message từ Kafka"""
        try:
            message_str = message_bytes.decode('utf-8')
            message = json.loads(message_str)
            
            # Extract 'after' field
            if 'payload' in message and 'after' in message['payload']:
                self.record_count += 1
                after = message['payload']['after']
                
                # Tính scores
                after['uv_score'] = ScoreCalculator.get_uv_score(after.get('uv_index'))
                after['air_pollution_score'] = ScoreCalculator.get_air_pollution_score(
                    after.get('carbon_monoxide'),
                    after.get('carbon_dioxide'),
                    after.get('nitrogen_dioxide'),
                    after.get('sulphur_dioxide')
                )
                after['heat_score'] = ScoreCalculator.get_heat_score(
                    after.get('temperature_2m'),
                    after.get('relative_humidity_2m')
                )
                after['environment_index'] = ScoreCalculator.get_environment_index(
                    after['air_pollution_score'],
                    after['uv_score'],
                    after['heat_score']
                )
                
                return after
            else:
                return None
        except Exception as e:
            print(f"Error parsing message: {e}", flush=True)
            return None


class WindowAggregator:
    """Tumbling window 10 giây + aggregation theo stop_id"""
    
    WINDOW_SIZE_SEC = 10
    
    def __init__(self, db_writer=None):
        self.windows = defaultdict(list)  # Key: (window_start, stop_id) -> list of records
        self.db_writer = db_writer        # PostgreSQL writer instance
        self.last_window_time = None
    
    def process_record(self, record):
        """Thêm record vào window tương ứng"""
        current_time = time.time()
        
        # Xác định window_start (làm tròn xuống 10 giây)
        window_start = int(current_time // self.WINDOW_SIZE_SEC) * self.WINDOW_SIZE_SEC
        window_end   = window_start + self.WINDOW_SIZE_SEC
        
        stop_id = record.get('stop_id')
        window_key = (window_start, stop_id)
        
        # Thêm record vào window
        self.windows[window_key].append({
            'record': record,
            'window_start': window_start,
            'window_end': window_end
        })
        
        # Kiểm tra xem có window nào hết hạn (> window_end) không
        self.check_and_flush_expired_windows(current_time)
        
        return window_key
    
    def check_and_flush_expired_windows(self, current_time):
        """Kiểm tra và flush các window đã hết hạn"""
        expired_keys = []
        for (window_start, stop_id), items in self.windows.items():
            window_end = window_start + self.WINDOW_SIZE_SEC
            # Nếu current_time vượt quá window_end + 1 giây (buffer) thì flush
            if current_time > window_end:
                expired_keys.append((window_start, stop_id))
        
        for key in expired_keys:
            self.flush_window(key)
    
    def flush_window(self, window_key):
        """Tính toán aggregation cho 1 window và in ra"""
        window_start, stop_id = window_key
        items = self.windows.pop(window_key)
        
        if not items:
            return
        
        window_end = window_start + self.WINDOW_SIZE_SEC
        
        # Lấy thông tin chung từ record đầu tiên
        first_record = items[0]['record']
        
        # Tính aggregation
        num_events = len(items)
        air_pollution_scores = [item['record'].get('air_pollution_score', 0) for item in items]
        uv_scores = [item['record'].get('uv_score', 0) for item in items]
        heat_scores = [item['record'].get('heat_score', 0) for item in items]
        env_indices = [item['record'].get('environment_index', 0) for item in items]
        
        avg_air_pollution = sum(air_pollution_scores) / len(air_pollution_scores) if air_pollution_scores else 0
        avg_uv = sum(uv_scores) / len(uv_scores) if uv_scores else 0
        avg_heat = sum(heat_scores) / len(heat_scores) if heat_scores else 0
        avg_env_index = sum(env_indices) / len(env_indices) if env_indices else 0
        
        # Format output
        output = {
            'window_start': datetime.fromtimestamp(window_start).isoformat(),
            'window_end': datetime.fromtimestamp(window_end).isoformat(),
            'stop_id': first_record.get('stop_id'),
            'stop_name': first_record.get('stop_name'),
            'location_name': first_record.get('location_name'),
            'stop_lat': first_record.get('stop_lat'),
            'stop_lon': first_record.get('stop_lon'),
            'num_events': num_events,
            'avg_air_pollution_score': round(avg_air_pollution, 4),
            'avg_uv_score': round(avg_uv, 4),
            'avg_heat_score': round(avg_heat, 4),
            'avg_environment_index': round(avg_env_index, 4)
        }
        
        # Ghi vào PostgreSQL
        if self.db_writer:
            self.db_writer.insert_window_result(output)
        
        # In kết quả
        print("\n" + "=" * 80)
        print(f"[WINDOW RESULT] {output['window_start']} → {output['window_end']}")
        print("=" * 80)
        print(json.dumps(output, ensure_ascii=False, indent=2), flush=True)
        print("=" * 80 + "\n")
    
    def flush_all(self):
        """Flush tất cả remaining windows"""
        for key in list(self.windows.keys()):
            self.flush_window(key)


def main():
    print("\n" + "=" * 80)
    print("Kafka Consumer with Environment Index & Window Aggregation")
    print("=" * 80)
    
    # 0) Tạo PostgreSQL writer
    print("\n[STEP 0] Initializing PostgreSQL writer...")
    try:
        db_writer = PostgreSQLWriter()
    except Exception as e:
        print(f"  ✗ Failed to initialize PostgreSQL writer: {e}")
        raise
    
    # 1) Tạo Kafka consumer
    print("\n[STEP 1] Creating Kafka consumer...")
    try:
        consumer = KafkaConsumer(
            'busdb.public.bus_data',
            bootstrap_servers=['kafka:9092'],
            group_id='env-window-aggregator-final',
            auto_offset_reset='earliest',
            value_deserializer=lambda m: m,  # Keep as bytes
            consumer_timeout_ms=30000,       # Timeout 30 giây
            session_timeout_ms=10000,
            heartbeat_interval_ms=3000,
            max_poll_records=100
        )
        print("  ✓ Kafka consumer created and connected")
    except Exception as e:
        print(f"  ✗ Failed to create Kafka consumer: {e}")
        db_writer.close()
        raise
    
    # 2) Tạo processor và aggregator
    print("\n[STEP 2] Initializing processors...")
    processor = DebeziumMessageProcessor()
    aggregator = WindowAggregator(db_writer=db_writer)
    print("  ✓ Processor and Aggregator initialized")
    
    print("\n" + "=" * 80)
    print("Reading from Kafka topic: busdb.public.bus_data")
    print(f"Window size: {WindowAggregator.WINDOW_SIZE_SEC} seconds")
    print("=" * 80 + "\n")
    
    # 3) Consume messages
    try:
        print("Waiting for messages...\n", flush=True)
        message_count = 0
        last_print_time = time.time()
        
        for message in consumer:
            record = processor.process(message.value)
            if record is not None:
                message_count += 1
                # Process through window aggregator
                aggregator.process_record(record)
                
                # In thông tin progress mỗi 10 records hoặc mỗi 5 giây
                current_time = time.time()
                if message_count % 10 == 0 or (current_time - last_print_time) > 5:
                    print(f"  [Processed {message_count} records...]", flush=True)
                    last_print_time = current_time
        
        # Flush all remaining windows
        print("\n✓ Message stream ended. Flushing remaining windows...", flush=True)
        aggregator.flush_all()
        
        print(f"\n✓ All messages processed. Total: {processor.record_count} records", flush=True)
    
    except KeyboardInterrupt:
        print("\n\n✓ Consumer stopped by user")
        print("Flushing remaining windows...")
        aggregator.flush_all()
    except Exception as e:
        print(f"✗ Error during message consumption: {e}")
        import traceback
        traceback.print_exc()
        raise
    finally:
        consumer.close()
        db_writer.close()
        print(f"\n✓ Consumer and database connections closed")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\n✗ ERROR: {e}", flush=True)
        sys.exit(1)
