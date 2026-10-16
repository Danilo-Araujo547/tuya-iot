"""Cached outdoor weather, separate from indoor sensor measurements."""
import math
import os
import threading
import time

import httpx
from fastapi import HTTPException

_lock = threading.Lock()
_cached = None
_retry_after = 0


def outdoor_weather():
    global _cached, _retry_after
    with _lock:
        now = time.time()
        if _cached and now - _cached['fetched_at'] < 600:
            return {**_cached, 'stale': False}
        if now >= _retry_after:
            try:
                response = httpx.get('https://api.open-meteo.com/v1/forecast', params={
                    'latitude': os.getenv('WEATHER_LATITUDE', '-20.42278'),
                    'longitude': os.getenv('WEATHER_LONGITUDE', '-49.97278'),
                    'current': 'temperature_2m,is_day,weather_code',
                    'timezone': 'UTC', 'timeformat': 'unixtime', 'forecast_days': 1,
                }, timeout=8)
                response.raise_for_status()
                current = response.json()['current']
                value = current['temperature_2m']
                observed = current['time']
                if (isinstance(value, bool) or not isinstance(value, (int, float))
                        or not math.isfinite(value) or not -90 <= value <= 65
                        or not isinstance(observed, (int, float)) or not math.isfinite(observed)
                        or not 0 <= now - observed <= 7200):
                    raise ValueError('Invalid weather reading')
                _cached = {'temperature': value, 'observed': observed, 'fetched_at': now,
                           'is_day': current.get('is_day') == 1,
                           'weather_code': current.get('weather_code'), 'source': 'Open-Meteo'}
                _retry_after = 0
                return {**_cached, 'stale': False}
            except (httpx.HTTPError, ValueError, KeyError, TypeError):
                _retry_after = now + 60
        if _cached and now - _cached['observed'] <= 7200:
            return {**_cached, 'stale': True}
        raise HTTPException(503, 'Temperatura externa indisponível no momento')
