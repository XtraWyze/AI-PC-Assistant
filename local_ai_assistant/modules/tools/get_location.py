"""Lightweight IP-based geolocation helper for Wyzer."""
from __future__ import annotations

from typing import Any, Dict, Optional

import requests

_IPINFO_URL = "https://ipinfo.io/json"
_TIMEOUT_SECONDS = 5


def _parse_coordinates(raw: Optional[str]) -> Dict[str, Optional[float]]:
    if not raw:
        return {"lat": None, "lon": None}
    try:
        lat_str, lon_str = (value.strip() for value in raw.split(",", maxsplit=1))
        lat = float(lat_str)
        lon = float(lon_str)
    except (ValueError, TypeError):
        return {"lat": None, "lon": None}
    return {"lat": lat, "lon": lon}


def get_location() -> Dict[str, Any]:
    """Return the user's approximate city/region/country and coordinates."""
    try:
        response = requests.get(_IPINFO_URL, timeout=_TIMEOUT_SECONDS)
        response.raise_for_status()
        payload = response.json()
    except requests.RequestException as exc:  # pragma: no cover - network edge cases
        raise RuntimeError(f"ipinfo.io request failed: {exc}") from exc
    except ValueError as exc:  # pragma: no cover - JSON edge cases
        raise RuntimeError("ipinfo.io returned invalid JSON") from exc

    coords = _parse_coordinates(payload.get("loc"))
    return {
        "city": payload.get("city") or "",
        "region": payload.get("region") or "",
        "country": payload.get("country") or "",
        "lat": coords["lat"],
        "lon": coords["lon"],
    }
