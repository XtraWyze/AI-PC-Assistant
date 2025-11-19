"""Weather and environment lookup helpers backed by Open-Meteo."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

import requests

_BASE_URL = "https://api.open-meteo.com/v1/forecast"
_AIR_QUALITY_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"
_TIMEOUT_SECONDS = 10

_WEATHER_CODE_MAP = {
    0: "clear sky",
    1: "mostly clear",
    2: "partly cloudy",
    3: "overcast",
    45: "foggy",
    48: "freezing fog",
    51: "light drizzle",
    53: "moderate drizzle",
    55: "dense drizzle",
    56: "light freezing drizzle",
    57: "freezing drizzle",
    61: "light rain",
    63: "moderate rain",
    65: "heavy rain",
    66: "light freezing rain",
    67: "freezing rain",
    71: "light snow",
    73: "moderate snow",
    75: "heavy snow",
    77: "snow grains",
    80: "light rain showers",
    81: "rain showers",
    82: "violent rain showers",
    85: "light snow showers",
    86: "snow showers",
    95: "thunderstorm",
    96: "thunderstorm with hail",
    99: "severe thunderstorm with hail",
}

_SEVERE_WEATHER_CODES = {
    65,
    75,
    82,
    86,
    95,
    96,
    99,
}


def _normalize_coordinate(value: Any, label: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be a valid number") from exc


def _normalize_days(days: Any, default: int = 3) -> int:
    try:
        value = int(days)
    except (TypeError, ValueError):
        value = default
    return max(1, min(value, 7))


def _describe_weather(code: int) -> str:
    return _WEATHER_CODE_MAP.get(code, "unknown conditions")


def _to_fahrenheit(value: Any) -> Optional[float]:
    try:
        return (float(value) * 9 / 5) + 32
    except (TypeError, ValueError):
        return None


def _format_clock(iso_timestamp: Optional[str]) -> Optional[str]:
    if not iso_timestamp:
        return None
    try:
        dt_value = datetime.fromisoformat(iso_timestamp.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt_value.strftime("%I:%M %p").lstrip("0")


def _safe_sequence_value(seq: Any, index: int) -> Optional[Any]:
    if not isinstance(seq, (list, tuple)):
        return None
    if index < 0 or index >= len(seq):
        return None
    return seq[index]


def _perform_request(url: str, params: Dict[str, Any]) -> Dict[str, Any]:
    try:
        response = requests.get(url, params=params, timeout=_TIMEOUT_SECONDS)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as exc:  # pragma: no cover - network issues
        raise RuntimeError(f"Open-Meteo request failed: {exc}") from exc
    except ValueError as exc:  # pragma: no cover - JSON issues
        raise RuntimeError("Open-Meteo returned invalid JSON") from exc


def _extract_current_humidity(payload: Dict[str, Any], current_time: Optional[str]) -> Optional[float]:
    hourly = payload.get("hourly") or {}
    humidity_values = hourly.get("relativehumidity_2m")
    times = hourly.get("time")
    if not (isinstance(humidity_values, list) and isinstance(times, list) and current_time):
        return None
    try:
        idx = times.index(current_time)
    except ValueError:
        idx = len(humidity_values) - 1
    return _safe_sequence_value(humidity_values, idx)


def _categorize_aqi(aqi: Optional[float]) -> Optional[str]:
    if aqi is None:
        return None
    try:
        value = float(aqi)
    except (TypeError, ValueError):
        return None
    if value <= 50:
        return "Good"
    if value <= 100:
        return "Moderate"
    if value <= 150:
        return "Unhealthy for Sensitive Groups"
    if value <= 200:
        return "Unhealthy"
    if value <= 300:
        return "Very Unhealthy"
    return "Hazardous"


def _latest_hourly_value(hourly: Dict[str, Any], key: str) -> Optional[Any]:
    values = hourly.get(key)
    if not isinstance(values, list) or not values:
        return None
    return values[-1]


def _build_alerts(
    current_weather: Optional[Dict[str, Any]],
    forecast: Optional[Dict[str, Any]],
    air_quality: Optional[Dict[str, Any]],
) -> List[str]:
    alerts: List[str] = []

    if air_quality:
        category = air_quality.get("aqi_category")
        if category and category not in {"Good", "Moderate"}:
            alerts.append(f"Air quality is {category.lower()} right now.")

    days = (forecast or {}).get("days") or []
    for entry in days:
        date = entry.get("date")
        temp_max = entry.get("temp_max_c")
        temp_min = entry.get("temp_min_c")
        code = entry.get("weather_code")
        if isinstance(temp_max, (int, float)) and temp_max >= 32:
            alerts.append(f"Expect very hot conditions (≈{temp_max:.0f}°C) on {date}.")
        if isinstance(temp_min, (int, float)) and temp_min <= 0:
            alerts.append(f"Below-freezing temperatures (≈{temp_min:.0f}°C) forecast on {date}.")
        if isinstance(code, int) and code in _SEVERE_WEATHER_CODES:
            alerts.append(f"Severe weather ({entry.get('summary', 'stormy conditions')}) possible on {date}.")

    humidity = (current_weather or {}).get("humidity_percent")
    if isinstance(humidity, (int, float)) and humidity >= 85:
        alerts.append("Humidity is high; expect it to feel muggy.")

    return alerts


def get_weather(lat: Any, lon: Any) -> Dict[str, Any]:
    """Return the current weather for the provided coordinates."""
    latitude = _normalize_coordinate(lat, "lat")
    longitude = _normalize_coordinate(lon, "lon")

    params = {
        "latitude": latitude,
        "longitude": longitude,
        "current_weather": True,
        "hourly": "relativehumidity_2m",
        "forecast_days": 1,
    }

    payload = _perform_request(_BASE_URL, params)

    current = payload.get("current_weather") or {}
    if not current:
        raise RuntimeError("Open-Meteo response missing current weather data")

    try:
        weather_code = int(current.get("weathercode", 0))
    except (TypeError, ValueError):
        weather_code = 0
    temp_c = current.get("temperature")
    temp_f = _to_fahrenheit(temp_c)
    humidity = _extract_current_humidity(payload, current.get("time"))

    return {
        "temperature_c": temp_c,
        "temperature_f": temp_f,
        "windspeed": current.get("windspeed"),
        "weather_code": weather_code,
        "description": _describe_weather(weather_code),
        "humidity_percent": humidity,
    }


def get_sunrise_sunset(lat: Any, lon: Any) -> Dict[str, Any]:
    latitude = _normalize_coordinate(lat, "lat")
    longitude = _normalize_coordinate(lon, "lon")

    params = {
        "latitude": latitude,
        "longitude": longitude,
        "daily": "sunrise,sunset",
        "timezone": "auto",
        "forecast_days": 1,
    }

    payload = _perform_request(_BASE_URL, params)
    daily = payload.get("daily") or {}
    sunrise = _safe_sequence_value(daily.get("sunrise"), 0)
    sunset = _safe_sequence_value(daily.get("sunset"), 0)
    if not (sunrise and sunset):
        raise RuntimeError("Open-Meteo response missing sunrise/sunset data")

    return {
        "sunrise": sunrise,
        "sunset": sunset,
        "sunrise_local": _format_clock(sunrise),
        "sunset_local": _format_clock(sunset),
    }


def get_forecast(lat: Any, lon: Any, days: Any = 3) -> Dict[str, Any]:
    latitude = _normalize_coordinate(lat, "lat")
    longitude = _normalize_coordinate(lon, "lon")
    normalized_days = _normalize_days(days, default=3)

    params = {
        "latitude": latitude,
        "longitude": longitude,
        "daily": "weathercode,apparent_temperature_max,apparent_temperature_min",
        "forecast_days": normalized_days,
        "timezone": "auto",
    }

    payload = _perform_request(_BASE_URL, params)
    daily = payload.get("daily") or {}
    times = daily.get("time") or []
    max_values = daily.get("apparent_temperature_max") or []
    min_values = daily.get("apparent_temperature_min") or []
    codes = daily.get("weathercode") or []

    summaries: List[Dict[str, Any]] = []
    for idx, date in enumerate(times[:normalized_days]):
        code_value = _safe_sequence_value(codes, idx)
        try:
            weather_code = int(code_value) if code_value is not None else None
        except (TypeError, ValueError):
            weather_code = None
        entry = {
            "date": date,
            "temp_min_c": _safe_sequence_value(min_values, idx),
            "temp_max_c": _safe_sequence_value(max_values, idx),
            "weather_code": weather_code,
            "summary": _describe_weather(weather_code or 0),
        }
        summaries.append(entry)

    if not summaries:
        raise RuntimeError("Open-Meteo response missing forecast data")

    return {"days": summaries}


def get_air_quality(lat: Any, lon: Any) -> Dict[str, Any]:
    latitude = _normalize_coordinate(lat, "lat")
    longitude = _normalize_coordinate(lon, "lon")

    params = {
        "latitude": latitude,
        "longitude": longitude,
        "hourly": "us_aqi,pm10,pm2_5,carbon_monoxide,ozone,nitrogen_dioxide,sulphur_dioxide",
        "timezone": "auto",
    }

    payload = _perform_request(_AIR_QUALITY_URL, params)
    hourly = payload.get("hourly") or {}
    aqi_value = _latest_hourly_value(hourly, "us_aqi")
    if aqi_value is None:
        raise RuntimeError("Open-Meteo response missing AQI data")

    result = {
        "aqi": aqi_value,
        "aqi_category": _categorize_aqi(aqi_value),
        "pm10": _latest_hourly_value(hourly, "pm10"),
        "pm2_5": _latest_hourly_value(hourly, "pm2_5"),
        "ozone": _latest_hourly_value(hourly, "ozone"),
        "nitrogen_dioxide": _latest_hourly_value(hourly, "nitrogen_dioxide"),
        "sulphur_dioxide": _latest_hourly_value(hourly, "sulphur_dioxide"),
        "carbon_monoxide": _latest_hourly_value(hourly, "carbon_monoxide"),
    }
    return result


def get_environment_overview(lat: Any, lon: Any, days: Any = 3) -> Dict[str, Any]:
    latitude = _normalize_coordinate(lat, "lat")
    longitude = _normalize_coordinate(lon, "lon")
    normalized_days = _normalize_days(days, default=3)

    current_weather = get_weather(latitude, longitude)
    sun = get_sunrise_sunset(latitude, longitude)
    forecast = get_forecast(latitude, longitude, normalized_days)
    air_quality = get_air_quality(latitude, longitude)

    alerts = _build_alerts(current_weather, forecast, air_quality)

    return {
        "location": {"lat": latitude, "lon": longitude},
        "current_weather": current_weather,
        "sun": sun,
        "forecast": forecast,
        "air_quality": air_quality,
        "alerts": alerts,
    }
