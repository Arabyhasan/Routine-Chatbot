from __future__ import annotations

import weather_service


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


def test_current_weather_uses_geocoding_then_forecast(monkeypatch):
    calls = []

    def fake_get(url, params, timeout):
        calls.append((url, params, timeout))
        if url == weather_service.GEOCODING_URL:
            return FakeResponse({"results": [{"name": "Dhaka", "country": "Bangladesh", "latitude": 23.81, "longitude": 90.41}]})
        return FakeResponse({"current": {"temperature_2m": 30.0, "apparent_temperature": 35.0, "relative_humidity_2m": 78, "wind_speed_10m": 8.0, "weather_code": 2}})

    monkeypatch.setattr(weather_service.requests, "get", fake_get)

    result = weather_service.get_current_weather("Dhaka")

    assert "Dhaka, Bangladesh" in result
    assert "partly cloudy" in result
    assert "30.0°C" in result
    assert [call[0] for call in calls] == [weather_service.GEOCODING_URL, weather_service.FORECAST_URL]


def test_current_weather_requires_a_city():
    assert "provide a city" in weather_service.get_current_weather("").lower()
