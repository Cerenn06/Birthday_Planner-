# maps_api.py
from __future__ import annotations
from typing import Any, Dict, List, Optional, Tuple

import os
import requests
import streamlit as st
from urllib.parse import quote_plus

# --- Google endpoints ---------------------------------------------------------
GOOGLE_GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"
GOOGLE_PLACES_FIND_URL = "https://maps.googleapis.com/maps/api/place/findplacefromtext/json"
GOOGLE_PLACES_DETAILS_URL = "https://maps.googleapis.com/maps/api/place/details/json"
GOOGLE_PLACES_TEXTSEARCH_URL = "https://maps.googleapis.com/maps/api/place/textsearch/json"


# --- Helpers -----------------------------------------------------------------
def price_level_to_text(level: Optional[int]) -> Optional[str]:
    """0..4 → '₺'..'₺₺₺₺₺'"""
    if level is None:
        return None
    try:
        level = int(level)
    except Exception:
        return None
    level = max(0, min(4, level))
    return "₺" * (level + 1)


def build_maps_url_from_place_id(place_id: str) -> str:
    """Fallback Maps URL that always works with a place_id."""
    return f"https://www.google.com/maps/place/?q=place_id:{place_id}"


def maps_place_link_from_details(place_id: str, details: Dict[str, Any]) -> str:
    """
    Prefer the Places Details 'url' if present; otherwise fall back to place_id URL.
    """
    url = details.get("url")
    if isinstance(url, str) and url.strip():
        return url
    return build_maps_url_from_place_id(place_id)


def _http_get(url: str, params: Dict[str, Any]) -> Dict[str, Any]:
    """Thin wrapper around requests.get with a timeout and JSON parse."""
    try:
        r = requests.get(url, params=params, timeout=15)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        # Light debug logging without breaking the UI
        print(f"[maps_api] GET {url} failed: {e}")
        return {}


# --- Geocode city → (lat, lng) -----------------------------------------------
@st.cache_data(ttl=60 * 60 * 24, show_spinner=False)
def geocode_city(
    city: str,
    api_key: str,
    country_hint: Optional[str] = None,
    language: str = "tr",
) -> Optional[Tuple[float, float]]:
    if not city or not api_key:
        return None
    q = city if not country_hint else f"{city}, {country_hint}"
    params = {"address": q, "key": api_key, "language": language}
    data = _http_get(GOOGLE_GEOCODE_URL, params)
    results = data.get("results", [])
    if not results:
        return None
    loc = results[0]["geometry"]["location"]
    return float(loc["lat"]), float(loc["lng"])


# --- Find place from text → place_id -----------------------------------------
@st.cache_data(ttl=60 * 60 * 24, show_spinner=False)
def find_place_id(
    text_query: str,
    api_key: str,
    location_bias: Optional[Tuple[float, float]] = None,
    radius_m: int = 5000,
    language: str = "tr",
) -> Optional[str]:
    if not text_query or not api_key:
        return None
    params: Dict[str, Any] = {
        "input": text_query,
        "inputtype": "textquery",
        "fields": "place_id,name,formatted_address",
        "key": api_key,
        "language": language,
    }
    if location_bias:
        lat, lng = location_bias
        params["locationbias"] = f"circle:{max(1000, int(radius_m))}@{lat},{lng}"
    data = _http_get(GOOGLE_PLACES_FIND_URL, params)
    candidates = data.get("candidates", [])
    if not candidates:
        return None
    return candidates[0].get("place_id")


# --- Place details ------------------------------------------------------------
@st.cache_data(ttl=60 * 60 * 24, show_spinner=False)
def get_place_details(
    place_id: str,
    api_key: str,
    language: str = "tr",
) -> Optional[Dict[str, Any]]:
    if not place_id or not api_key:
        return None

    # Ask explicitly for readable weekday_text & open_now; include 'url' for pretty Maps link
    fields = ",".join([
        "name",
        "formatted_address",
        "rating",
        "user_ratings_total",
        "price_level",
        "opening_hours/weekday_text",
        "opening_hours/open_now",
        "website",
        "url",
        "geometry/location",
        "place_id",
    ])

    params = {"place_id": place_id, "fields": fields, "key": api_key, "language": language}
    data = _http_get(GOOGLE_PLACES_DETAILS_URL, params)
    status = data.get("status", "")
    if status != "OK":
        # Non-fatal debug line; avoids breaking UI while still surfacing quota/config issues
        print(f"[maps_api] Places Details status={status} error={data.get('error_message')}")
        return None

    r = data.get("result", {}) or {}
    loc = (r.get("geometry") or {}).get("location") or {}

    return {
        "place_id": r.get("place_id"),
        "name": r.get("name"),
        "formatted_address": r.get("formatted_address"),
        "rating": r.get("rating"),
        "user_ratings_total": r.get("user_ratings_total"),
        "price_level": r.get("price_level"),
        "price_text": price_level_to_text(r.get("price_level")),
        "opening_hours": {
            "weekday_text": ((r.get("opening_hours") or {}).get("weekday_text") or []),
            "open_now": ((r.get("opening_hours") or {}).get("open_now")),
        },
        "website": r.get("website"),
        "maps_url": maps_place_link_from_details(r.get("place_id", ""), r),
        "location": {"lat": loc.get("lat"), "lng": loc.get("lng")},
        "source": "google_places",
    }


# --- Text Search (first page) -------------------------------------------------
@st.cache_data(ttl=60 * 60 * 24, show_spinner=False)
def places_text_search(
    query: str,
    api_key: str,
    location_bias: Optional[Tuple[float, float]] = None,
    radius_m: int = 5000,
    max_results: int = 6,
    language: str = "tr",
) -> List[Dict[str, Any]]:
    """
    Places Text Search (one page). Returns [{'place_id','name'}, ...] up to max_results.
    Useful when LLM output is unavailable and we need seed venues.
    """
    if not query or not api_key:
        return []
    params: Dict[str, Any] = {"query": query, "key": api_key, "language": language}
    if location_bias:
        lat, lng = location_bias
        params["location"] = f"{lat},{lng}"
        params["radius"] = int(radius_m)

    data = _http_get(GOOGLE_PLACES_TEXTSEARCH_URL, params)
    results = (data.get("results") or [])[:max_results]

    out: List[Dict[str, Any]] = []
    for r in results:
        pid = r.get("place_id")
        nm = r.get("name")
        if pid and nm:
            out.append({"place_id": pid, "name": nm})
    return out
