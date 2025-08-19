# weather_api.py
from __future__ import annotations
from typing import Any, Dict, Optional, Tuple
from datetime import date, datetime
import math

import requests
import streamlit as st

# Prefer utils.maps_api.geocode_city; fall back to root maps_api
try:
    from utils.maps_api import geocode_city  # type: ignore
except Exception:
    from maps_api import geocode_city  # type: ignore

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
OPEN_METEO_GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"

# Simple mapping for Open-Meteo weather codes → short text + emoji
_WEATHER_CODE = {
    0:  ("Clear sky", "☀️"),
    1:  ("Mainly clear", "🌤️"),
    2:  ("Partly cloudy", "⛅"),
    3:  ("Overcast", "☁️"),
    45: ("Fog", "🌫️"),
    48: ("Depositing rime fog", "🌫️"),
    51: ("Light drizzle", "🌦️"),
    53: ("Drizzle", "🌦️"),
    55: ("Dense drizzle", "🌦️"),
    61: ("Slight rain", "🌧️"),
    63: ("Rain", "🌧️"),
    65: ("Heavy rain", "🌧️"),
    66: ("Light freezing rain", "🌧️"),
    67: ("Freezing rain", "🌧️"),
    71: ("Slight snow", "🌨️"),
    73: ("Snow", "🌨️"),
    75: ("Heavy snow", "🌨️"),
    77: ("Snow grains", "🌨️"),
    80: ("Rain showers", "🌧️"),
    81: ("Heavy rain showers", "🌧️"),
    82: ("Violent rain showers", "🌧️"),
    85: ("Snow showers", "🌨️"),
    86: ("Heavy snow showers", "🌨️"),
    95: ("Thunderstorm", "⛈️"),
    96: ("Thunderstorm w/ hail", "⛈️"),
    99: ("Thunderstorm w/ heavy hail", "⛈️"),
}

def _code_text_emoji(code: Optional[int]):
    if code is None:
        return ("", "")
    return _WEATHER_CODE.get(int(code), ("", ""))

def _http_get(url: str, params: Dict[str, Any]) -> Dict[str, Any]:
    try:
        r = requests.get(url, params=params, timeout=15)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"[weather_api] GET {url} failed: {e}")
        return {}

def _round1(x: Optional[float]) -> Optional[float]:
    try:
        return None if x is None else round(float(x), 1)
    except Exception:
        return None

def _clamp_hour(h: int) -> int:
    try:
        h = int(h)
    except Exception:
        h = 18
    return max(0, min(23, h))

def _nearest_hour_value(day_str: str, target_hour_local: int, times: list[str], values: list[Any]) -> Optional[float]:
    """Find value closest to `${day_str}T{HH}:00` within the same day."""
    if not times or not values:
        return None
    target = f"{day_str}T{target_hour_local:02d}:00"
    # exact match first
    for i, t in enumerate(times):
        if t == target and i < len(values):
            try:
                return float(values[i])
            except Exception:
                return None
    # nearest on same day
    best_idx, best_diff = None, 1e9
    for i, t in enumerate(times):
        if not t.startswith(day_str):
            continue
        try:
            hh = int(t[11:13])
            diff = abs(hh - target_hour_local)
            if diff < best_diff and i < len(values):
                best_idx, best_diff = i, diff
        except Exception:
            continue
    if best_idx is not None:
        try:
            return float(values[best_idx])
        except Exception:
            return None
    return None

# --------- fallback geocoder (no key needed) ----------
def _fallback_geocode_open_meteo(city: str, language: str = "tr") -> Optional[Tuple[float, float]]:
    """
    Use Open-Meteo's free geocoding if Google Geocoding fails or is unavailable.
    """
    if not city:
        return None
    data = _http_get(OPEN_METEO_GEOCODE_URL, {"name": city, "count": 1, "language": language, "format": "json"})
    try:
        r = (data.get("results") or [None])[0]
        if not r:
            return None
        return float(r["latitude"]), float(r["longitude"])
    except Exception:
        return None

@st.cache_data(ttl=60 * 60 * 2, show_spinner=False)
def get_forecast_for_date(
    city: str,
    when: date,
    maps_api_key: Optional[str] = None,
    target_hour_local: int = 18,
    radius_hint: Optional[int] = None,  # kept for symmetry, unused here
) -> Optional[Dict[str, Any]]:
    """
    Returns a dict with expected temperature for the given city & date:
      {
        'date': 'YYYY-MM-DD',
        'lat': float, 'lng': float,
        't_min_c': float | None,
        't_max_c': float | None,
        't_expected_c': float | None,   # hourly at target_hour_local (or nearest), else (min+max)/2
        'weathercode': int | None,
        'weather_text': str, 'weather_emoji': str,
        'source': 'open-meteo'
      }
    If the date is out of the forecast window or geocoding fails, returns None.
    """
    if not city:
        return None

    # 1) Geocode: Google first, then free fallback
    coords = geocode_city(city, maps_api_key or "")
    if not coords:
        coords = _fallback_geocode_open_meteo(city)
    if not coords:
        return None

    lat, lng = coords
    day_str = when.isoformat()

    # 2) Query Open-Meteo
    params = {
        "latitude": lat,
        "longitude": lng,
        "timezone": "auto",
        "start_date": day_str,
        "end_date": day_str,
        "daily": "temperature_2m_max,temperature_2m_min,weathercode",
        "hourly": "temperature_2m",
    }
    data = _http_get(OPEN_METEO_URL, params)
    if not data:
        return None

    daily = (data.get("daily") or {})
    hourly = (data.get("hourly") or {})

    # 3) Extract daily values
    tmin, tmax, wcode = None, None, None
    try:
        if (daily.get("time") or [None])[0] == day_str:
            tmin = float(daily.get("temperature_2m_min", [None])[0]) if daily.get("temperature_2m_min") else None
            tmax = float(daily.get("temperature_2m_max", [None])[0]) if daily.get("temperature_2m_max") else None
            wcode = int(daily.get("weathercode", [None])[0]) if daily.get("weathercode") else None
    except Exception:
        pass

    # 4) Hourly “expected” temp at target hour (or nearest)
    texp = None
    try:
        times = list(hourly.get("time") or [])
        temps = list(hourly.get("temperature_2m") or [])
        if times and temps:
            target_hour_local = _clamp_hour(target_hour_local)
            texp = _nearest_hour_value(day_str, target_hour_local, times, temps)
    except Exception:
        pass

    # 5) Fallback expected temp
    if texp is None and (tmin is not None and tmax is not None):
        texp = (tmin + tmax) / 2.0

    # Round
    tmin = _round1(tmin)
    tmax = _round1(tmax)
    texp = _round1(texp)

    wtext, wemoji = _code_text_emoji(wcode)

    if all(v is None for v in [tmin, tmax, texp, wcode]):
        return None

    return {
        "date": day_str,
        "lat": lat,
        "lng": lng,
        "t_min_c": tmin,
        "t_max_c": tmax,
        "t_expected_c": texp,
        "weathercode": wcode,
        "weather_text": wtext,
        "weather_emoji": wemoji,
        "source": "open-meteo",
    }

def format_weather_line(city: str, when: date, maps_api_key: Optional[str] = None, target_hour_local: int = 18) -> str:
    """
    Convenience helper for UI: returns a single pretty sentence or a fallback.
    """
    w = get_forecast_for_date(city, when, maps_api_key=maps_api_key, target_hour_local=target_hour_local)
    if not w:
        return f"Weather on {when.isoformat()} in {city}: not available."
    tmin, tmax, texp = w["t_min_c"], w["t_max_c"], w["t_expected_c"]
    emoji, txt = w["weather_emoji"], w["weather_text"]
    parts = []
    if emoji or txt:
        parts.append(f"{emoji} {txt}".strip())
    if texp is not None:
        parts.append(f"~{texp}°C")
    if tmin is not None and tmax is not None:
        parts.append(f"(min {tmin}°C / max {tmax}°C)")
    tail = ", ".join(parts) if parts else "no details"
    return f"Weather on {when.isoformat()} in {city}: {tail}."
