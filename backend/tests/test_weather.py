import time
from unittest.mock import Mock

import httpx
import pytest
from app import weather


@pytest.fixture(autouse=True)
def weather_cache(monkeypatch):
    monkeypatch.setattr(weather, '_cached', None)
    monkeypatch.setattr(weather, '_retry_after', 0)


def response(value=26.1):
    return Mock(json=lambda: {'current': {'temperature_2m': value, 'time': int(time.time()),
                                        'is_day': 1, 'weather_code': 3}})


def test_weather_auth_and_cache(client, logged, monkeypatch):
    fetch = Mock(return_value=response())
    monkeypatch.setattr(weather.httpx, 'get', fetch)
    for _ in range(2):
        result = logged.get('/api/v1/weather/current')
        assert result.status_code == 200
        assert result.json()['temperature'] == 26.1
        assert result.json()['source'] == 'Open-Meteo'
        assert result.json()['stale'] is False
        assert 'latitude' not in result.json()
    fetch.assert_called_once()
    logged.cookies.clear()
    assert client.get('/api/v1/weather/current').status_code == 401


def test_outage_preserves_old_reading_and_marks_stale(logged, monkeypatch):
    now = time.time()
    monkeypatch.setattr(weather, '_cached', {'temperature': 25, 'observed': now - 900,
                                          'fetched_at': now - 900, 'source': 'Open-Meteo'})
    fetch = Mock(side_effect=httpx.ReadTimeout('offline'))
    monkeypatch.setattr(weather.httpx, 'get', fetch)
    assert logged.get('/api/v1/weather/current').json()['stale'] is True
    assert logged.get('/api/v1/weather/current').json()['temperature'] == 25
    fetch.assert_called_once()
    weather._cached['observed'] = now - 7201
    assert logged.get('/api/v1/weather/current').status_code == 503


@pytest.mark.parametrize('value', [None, True, float('nan'), 100])
def test_invalid_weather_never_fabricates_temperature(logged, monkeypatch, value):
    monkeypatch.setattr(weather.httpx, 'get', Mock(return_value=response(value)))
    assert logged.get('/api/v1/weather/current').status_code == 503
