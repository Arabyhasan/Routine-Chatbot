"""Small Open-Meteo client used by the local Routine Agent MCP server."""
from __future__ import annotations

from typing import Any

import requests


GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
REQUEST_TIMEOUT_SECONDS = 10


def _get_json(url: str, params: dict[str, Any]) -> dict[str, Any]:
    response = requests.get(url, params=params, timeout=REQUEST_TIMEOUT_SECONDS)
    response.raise_for_status()
    return response.json()


def get_current_weather(city: str) -> str:
    """Return a concise live current-weather report for a city."""
    city = (city or "").strip()
    if not city:
        return "Please provide a city name, for example 'Dhaka, Bangladesh'."

    try:
        locations = _get_json(GEOCODING_URL, {"name": city, "count": 1}).get("results", [])
    except requests.RequestException as exc:
        return f"I could not look up '{city}' right now: {exc}"
    except ValueError:
        return "The weather service returned an unreadable location response. Please try again."

    if not locations:
        return f"I could not find a location named '{city}'. Try including its country."

    location = locations[0]
    try:
        forecast = _get_json(
            FORECAST_URL,
            {
                "latitude": location["latitude"],
                "longitude": location["longitude"],
                "current": "temperature_2m,apparent_temperature,relative_humidity_2m,wind_speed_10m,weather_code",
                "timezone": "auto",
            },
        )
        current = forecast["current"]
    except (KeyError, TypeError, ValueError):
        return "The weather service returned an incomplete forecast. Please try again."
    except requests.RequestException as exc:
        return f"I could not get the current weather for {location.get('name', city)}: {exc}"

    place = ", ".join(part for part in (location.get("name"), location.get("country")) if part)
    return (
        f"Current weather in {place}: {_weather_description(current.get('weather_code'))}; "
        f"{current['temperature_2m']}°C (feels like {current['apparent_temperature']}°C), "
        f"humidity {current['relative_humidity_2m']}%, wind {current['wind_speed_10m']} km/h."
    )


def _weather_description(code: int | None) -> str:
    """Translate Open-Meteo's WMO weather code into a short description."""
    descriptions = {
        0: "clear sky", 1: "mainly clear", 2: "partly cloudy", 3: "overcast",
        45: "foggy", 48: "foggy with rime", 51: "light drizzle", 53: "moderate drizzle",
        55: "heavy drizzle", 61: "light rain", 63: "moderate rain", 65: "heavy rain",
        71: "light snow", 73: "moderate snow", 75: "heavy snow", 80: "light rain showers",
        81: "moderate rain showers", 82: "violent rain showers", 95: "thunderstorm",
        96: "thunderstorm with light hail", 99: "thunderstorm with heavy hail",
    }
    return descriptions.get(code, "conditions unavailable")
