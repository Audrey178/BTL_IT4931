import pandas as pd
import numpy as np 
import os
from helpers import load_cfg
import openmeteo_requests
import requests_cache
from retry_requests import retry
from datetime import timedelta
from deltalake.writer import write_deltalake
from concurrent.futures import ThreadPoolExecutor, as_completed
import time
import random
from tqdm import tqdm

CFG_PATH = 'datalake/utils/config.yaml'

# Setup the Open-Meteo API client with cache and retry on error
cache_session = requests_cache.CachedSession('.cache', expire_after = 3600)
retry_session = retry(cache_session, retries = 5, backoff_factor = 0.2)
openmeteo = openmeteo_requests.Client(session = retry_session)


def fetch_air_weather(row):
    lat = row['stopLat']
    lon = row['stopLon']
    date = row['datetime']
    
    dt = pd.to_datetime(date, utc=True)
    start_time = (dt - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M")
    end_time = (dt + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M")

    
    try: 
        # ------------- API: air-quality -------------
        url = "https://air-quality-api.open-meteo.com/v1/air-quality"
        params = {
	        "latitude": lat,
	        "longitude": lon,
	        "hourly": ["carbon_monoxide", "carbon_dioxide", "nitrogen_dioxide", "sulphur_dioxide", "uv_index_clear_sky", "uv_index"],
            "start": start_time,
            "end": end_time,
        }
        air_responses = openmeteo.weather_api(url, params=params)

        response = air_responses[0]

        air_hourly = response.Hourly()

        air_times = pd.date_range(
            start=pd.to_datetime(air_hourly.Time(), unit="s", utc=True),
            end=pd.to_datetime(air_hourly.TimeEnd(), unit="s", utc=True),
            freq=pd.Timedelta(seconds=air_hourly.Interval()),
            inclusive="left"
        )

        air_df = pd.DataFrame({
            "datetime_utc": air_times,
            "carbon_monoxide": air_hourly.Variables(0).ValuesAsNumpy(),
            "carbon_dioxide": air_hourly.Variables(1).ValuesAsNumpy(),
            "nitrogen_dioxide": air_hourly.Variables(2).ValuesAsNumpy(),
            "sulphur_dioxide": air_hourly.Variables(3).ValuesAsNumpy(),
            "uv_index_clear_sky": air_hourly.Variables(4).ValuesAsNumpy(),
            "uv_index": air_hourly.Variables(5).ValuesAsNumpy(),
        })
    
        # ------------- API: weather -------------
        weather_params = {
            "latitude": lat,
            "longitude": lon,
            "hourly": ["temperature_2m", "relative_humidity_2m", "precipitation", "windspeed_10m", "winddirection_10m"],
            "start": start_time,
            "end": end_time,
        }
        weather_responses = openmeteo.weather_api("https://api.open-meteo.com/v1/forecast", params=weather_params)

        weather_response = weather_responses[0]
    
        weather_hourly = weather_response.Hourly()
        weather_times = pd.date_range(
            start=pd.to_datetime(weather_hourly.Time(), unit="s", utc=True),
            end=pd.to_datetime(weather_hourly.TimeEnd(), unit="s", utc=True),
            freq=pd.Timedelta(seconds=weather_hourly.Interval()),
            inclusive="left"
        )
        
        weather_df = pd.DataFrame({
            "datetime_utc": weather_times,
            "temperature_2m": weather_hourly.Variables(0).ValuesAsNumpy(),
            "relative_humidity_2m": weather_hourly.Variables(1).ValuesAsNumpy(),
            "precipitation": weather_hourly.Variables(2).ValuesAsNumpy(),
            "windspeed_10m": weather_hourly.Variables(3).ValuesAsNumpy(),
            "winddirection_10m": weather_hourly.Variables(4).ValuesAsNumpy(),
        })
        
        merged_df = pd.merge_asof(air_df.sort_values("datetime_utc"), weather_df.sort_values("datetime_utc"))
        target_time = pd.to_datetime(date, utc=True)
        closest_row = merged_df.iloc[(merged_df['datetime_utc'] - target_time).abs().argmin()]
        combined = {**row.to_dict(), **closest_row.drop(labels=['datetime_utc']).to_dict()}
        
        time.sleep(random.uniform(0.2, 0.5))
        return combined
    
    except Exception as e:
        print(f"[Error] {e} for row with datetime {date}, lat {lat}, lon {lon}")
        return None



def parallel_fetch(df, max_workers=10):
    """Fetch data in parallel with progress bar"""
    results = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(fetch_air_weather, row): idx for idx, row in df.iterrows()}
        for future in tqdm(as_completed(futures), total=len(futures), desc="Fetching data"):
            try:
                res = future.result()
                if res is not None:
                    results.append(res)
            except Exception as e:
                print(f"[ThreadError] {e}")
    if not results:
        return pd.DataFrame()
    return pd.DataFrame(results)

if __name__ == "__main__":
    cfg = load_cfg(CFG_PATH)
    bus_data_path = cfg['bus_data']['folder_path']
    output_path = cfg['datalake_iot']['folder_path']
    os.makedirs(output_path, exist_ok=True)

    all_files = [f for f in os.listdir(bus_data_path) if f.endswith('.csv')]

    for file in all_files:
        file_path = os.path.join(bus_data_path, file)
        df = pd.read_csv(file_path)

        enriched_df = parallel_fetch(df, max_workers=8)  

        if not enriched_df.empty:
            write_deltalake(output_path, enriched_df, mode='append')
