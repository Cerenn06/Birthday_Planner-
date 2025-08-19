# agents/venue_agent.py
from __future__ import annotations
from typing import Any, Dict, List, Optional, Tuple
import os
import re

from .base_agent import BaseAgent

# Optional prompt import (falls back to inline if missing)
try:
    from prompts.venue_prompts import VENUE_SEARCH_PROMPT  # type: ignore
except Exception:
    VENUE_SEARCH_PROMPT = None  # type: ignore

# Maps helpers: prefer utils/, fallback to project root
try:
    from utils.maps_api import (
        geocode_city,
        find_place_id,
        get_place_details,
        places_text_search,
    )
except Exception:
    from maps_api import (  # type: ignore
        geocode_city,
        find_place_id,
        get_place_details,
        places_text_search,
    )

# Weather helper
try:
    from utils.weather_api import format_weather_line  # type: ignore
except Exception:
    from weather_api import format_weather_line  # type: ignore


def _normalize_tr(s: str) -> str:
    if not isinstance(s, str):
        return ""
    table = str.maketrans({
        "ı": "i", "İ": "i", "ş": "s", "Ş": "s", "ğ": "g", "Ğ": "g",
        "ü": "u", "Ü": "u", "ö": "o", "Ö": "o", "ç": "c", "Ç": "c",
    })
    return s.translate(table).casefold()


def _in_city(addr: str, city: str) -> bool:
    """True if normalized city substring appears in normalized address."""
    if not addr or not city:
        return False
    return _normalize_tr(city) in _normalize_tr(addr)


def _is_outdoor_type(venue_type: str) -> bool:
    """Returns True when user selected 'Outdoor'."""
    return (venue_type or "").strip().lower() == "outdoor"


class VenueAgent(BaseAgent):
    """Suggest venues and enrich them with Google Places details."""

    def __init__(self) -> None:
        super().__init__(
            name="venue_agent",
            description="Planner for venue suggestions",
            instruction=(
                "You are the Venue agent. Suggest suitable venues only. "
                "Provide specific venue names that exist in the real world. "
                "Always consider weather conditions when making suggestions."
            ),
        )

        # Streamlit secrets (optional) → env fallback
        try:
            import streamlit as st  # type: ignore
            _secret_maps = st.secrets.get("GOOGLE_MAPS_API_KEY") or st.secrets.get("GOOGLE_API_KEY")
            _secret_gemini = st.secrets.get("GOOGLE_API_KEY")
        except Exception:
            _secret_maps = None
            _secret_gemini = None

        self.google_api_key = (
            _secret_maps
            or os.getenv("GOOGLE_MAPS_API_KEY")
            or os.getenv("GOOGLE_API_KEY")
            or ""
        )
        self.gemini_api_key = _secret_gemini or os.getenv("GOOGLE_API_KEY", "")
        self.gemini_model = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")

    # ───────────────────────── LLM plumbing  ─────────────────────────
    def _call_llm_unified(self, prompt: str, ctx: Dict[str, Any]) -> Optional[str]:
        try:
            return self.generate_text(prompt, max_output_tokens=900)
        except Exception:
            pass

        # Optional legacy fallback
        if self.gemini_api_key:
            try:
                import google.generativeai as genai  # type: ignore
                genai.configure(api_key=self.gemini_api_key)
                model = genai.GenerativeModel(self.gemini_model or self.model)
                resp = model.generate_content(prompt)
                text = getattr(resp, "text", None)
                return text if text is not None else str(resp)
            except Exception:
                pass

        return None

    # ───────────────────────── Cuisine match helper ─────────────────────────
    def _matches_cuisine(self, det: Dict[str, Any], cuisine: str) -> bool:
        """Heuristic check if a Place Details object matches the requested cuisine."""
        if not cuisine:
            return True
        ckey = cuisine.strip().lower()

        CUISINE_KEYS = {
            "italian": ["italian", "italiano", "italyan", "ristorante", "trattoria", "pizzeria", "pizza", "pasta"],
            "turkish": ["turkish", "türk", "lokanta", "kebap", "ocakbaşı", "meze"],
            "mediterranean": ["mediterranean", "akdeniz"],
            "asian": ["asian", "asya", "sushi", "ramen", "thai", "korean", "kore", "japanese", "japon"],
            "mixed": ["mixed", "international", "uluslararasi"],
        }
        keys = CUISINE_KEYS.get(ckey, [ckey])

        # Native field if present
        serves = det.get("serves_cuisine")
        if isinstance(serves, list) and any(str(s).lower() in keys for s in serves):
            return True

        ed = det.get("editorial_summary") or {}
        overview = (ed.get("overview") or "") if isinstance(ed, dict) else ""
        types = det.get("types") or []
        if isinstance(types, list):
            types = " ".join(types)

        hay = " ".join([
            str(det.get("name") or ""),
            str(det.get("formatted_address") or ""),
            overview,
            str(types),
            str(det.get("website") or ""),
        ]).lower()

        return any(k in hay for k in keys)

    # ───────────────────────── Extraction helpers ─────────────────────────
    def _extract_venue_names_from_text(self, text: str) -> List[str]:
        if not text:
            return []
        venue_names: List[str] = []

        # **Name** or **Name (Area)** patterns
        for match in re.findall(r"\*\*([^*]+?)\*\*\s*[:\-]?", text):
            name = re.sub(r"\s*\([^)]*\)\s*", "", match).strip()
            if len(name) > 2:
                venue_names.append(name)

        # Bullet lines like "- **Name**"
        for line in text.splitlines():
            s = line.strip()
            if s.startswith(("*", "-")):
                m = re.search(r"\*\*([^*]+?)\*\*", s)
                if m:
                    name = re.sub(r"\s*\([^)]*\)\s*", "", m.group(1)).strip()
                    if len(name) > 2:
                        venue_names.append(name)

        # de-dup preserving order
        seen = set()
        out: List[str] = []
        for n in venue_names:
            k = n.lower()
            if k not in seen:
                out.append(n)
                seen.add(k)
        return out[:3]

    # ───────────────────────── Places searching ─────────────────────────
    def _search_venue_in_places(self, venue_name: str, city: str, cuisine: str = "") -> Optional[Dict[str, Any]]:
        """
        Resolve a given LLM-suggested venue name to full Place Details.
        Always fetch details before matching (Text Search lacks address).
        """
        if not self.google_api_key:
            return None

        center = geocode_city(city, self.google_api_key) if city else None

        queries = [
            f"{venue_name} {city}",
            venue_name,
            f"{venue_name} venue {city}",
            f"{venue_name} restaurant {city}",
        ]

        ckey = (cuisine or "").strip().lower()
        best: Tuple[int, Optional[Dict[str, Any]]] = (-1, None)  # (score, details)

        for q in queries:
            try:
                seeds = places_text_search(
                    query=q,
                    api_key=self.google_api_key,
                    location_bias=center,
                    radius_m=20000,
                    max_results=8,
                )
            except Exception:
                continue

            for s in seeds:
                pid = s.get("place_id")
                if not pid:
                    continue
                try:
                    det = get_place_details(pid, self.google_api_key)
                except Exception:
                    det = None
                if not det:
                    continue

                name = (det.get("name") or "").lower()
                addr = det.get("formatted_address") or ""
                # simple score: name word overlap + city match bonus
                name_words = set(venue_name.lower().split())
                overlap = len(name_words.intersection(set(name.split())))
                score = overlap
                if _in_city(addr, city):
                    score += 2
                # cuisine preference
                if ckey:
                    if self._matches_cuisine(det, ckey):
                        score += 3
                    else:
                        score -= 2

                if score > best[0]:
                    best = (score, det)

        return best[1]

    def _get_fallback_venues(self, city: str, venue_type: str, audience: str, cuisine: str = "", is_outdoor: bool = False) -> List[Dict[str, Any]]:
        """Get fallback venue suggestions using Places Text Search + Details."""
        if not self.google_api_key:
            return []

        center = geocode_city(city, self.google_api_key) if city else None
        seeds: List[Dict[str, Any]] = []

        # Baseline terms
        base_terms = {
            "indoor": ["restaurant", "cafe", "party hall", "event venue"],
            "outdoor": ["park", "garden", "beach club", "terrace"],
            "hybrid": ["restaurant with terrace", "event space", "venue"],
        }

        if is_outdoor:
            # Outdoor: ignore cuisine; prioritize open-air places
            outdoor_terms = [
                "park", "garden", "botanical garden", "zoo",
                "beach", "beach club", "outdoor event space",
                "promenade", "terrace", "viewing terrace",
                # Turkish variants:
                "piknik alanı", "mesire alanı", "çocuk parkı", "seyir terası",
                "koru", "kent ormanı", "tabiat parkı",
            ]
            queries = [f"{t} {city}" for t in outdoor_terms]
        else:
            CUISINE_TERMS = {
                "italian": ["italian restaurant", "italyan restoran", "pizzeria", "trattoria"],
                "turkish": ["turkish restaurant", "türk restoran", "lokanta"],
                "mediterranean": ["mediterranean restaurant", "akdeniz restoran"],
                "asian": ["asian restaurant", "asya restoran", "sushi", "ramen"],
                "mixed": ["international restaurant", "mixed cuisine"],
            }
            ckey = (cuisine or "").strip().lower()
            cuisine_terms = CUISINE_TERMS.get(ckey, [ckey] if ckey else [])

            queries: List[str] = []
            # Cuisine-first queries
            for term in cuisine_terms:
                queries.append(f"{term} {city}")
            # Then generic venue_type terms (with/without cuisine)
            for term in base_terms.get(venue_type.lower(), ["venue", "restaurant"]):
                if ckey:
                    queries.append(f"{ckey} {term} {city}")
                queries.append(f"{term} {city}")

        # Run text search
        for q in queries:
            if len(seeds) >= 12:
                break
            try:
                seeds.extend(places_text_search(
                    query=q,
                    api_key=self.google_api_key,
                    location_bias=center,
                    radius_m=20000 if is_outdoor else 15000,
                    max_results=4,
                ))
            except Exception:
                continue

        # Details + city (and cuisine if not outdoor)
        results: List[Dict[str, Any]] = []
        for s in seeds:
            if len(results) >= 3:
                break
            pid = s.get("place_id")
            if not pid:
                continue
            det = get_place_details(pid, self.google_api_key)
            if not det:
                continue
            if not _in_city(det.get("formatted_address", ""), city):
                continue

            if (not is_outdoor) and cuisine:
                if not self._matches_cuisine(det, cuisine):
                    continue

            results.append(det)
        return results

    # ───────────────────────── Weather + formatting ─────────────────────────
    def _get_weather_line(self, ctx: Dict[str, Any]) -> str:
        w = (ctx.get("weather_forecast_text") or "").strip()
        if w:
            return w

        city = ctx.get("city", "")
        when = ctx.get("event_date") or ctx.get("date") or ctx.get("selected_date")

        from datetime import date as _date
        if isinstance(when, str) and len(when) >= 10:
            try:
                y, m, d = map(int, when[:10].split("-"))
                when = _date(y, m, d)
            except Exception:
                when = None

        if city and when:
            return format_weather_line(city, when, maps_api_key=self.google_api_key, target_hour_local=18)
        return "Weather information not available - please check local forecast"

    def _format_weather_and_venues(self, weather_info: str, venues: List[Dict[str, Any]], city: str) -> str:
        parts: List[str] = []
        if weather_info:
            parts.append(f"📅 **Weather:** {weather_info}")
            parts.append("")

        if not venues:
            parts.append("❌ No suitable venues found. Please try different search criteria.")
            return "\n".join(parts)

        parts.append(f"📍 **Recommended Venues in {city}:**")
        parts.append("")

        for i, v in enumerate(venues, 1):
            name = v.get("name") or "Unknown Venue"
            parts.append(f"**{i}. {name}**")

            addr = v.get("formatted_address") or f"{city} (address not available)"
            parts.append(f"📌 **Address:** {addr}")

            rating = v.get("rating")
            reviews = v.get("user_ratings_total")
            meta_bits: List[str] = []
            if rating is not None:
                meta_bits.append(f"⭐ {rating}/5" + (f" ({reviews} reviews)" if reviews else ""))
            price_text = v.get("price_text")
            if price_text:
                meta_bits.append(f"💰 {price_text}")
            if meta_bits:
                parts.append(" · ".join(meta_bits))

            maps_url = v.get("maps_url")
            if maps_url:
                parts.append(f"🗺️ **Google Maps:** {maps_url}")

            if v.get("website"):
                parts.append(f"🌐 **Website:** {v['website']}")

            oh = v.get("opening_hours") or {}
            weekday_text = oh.get("weekday_text") or []
            if isinstance(weekday_text, list) and weekday_text:
                hours_md = "\n".join(f"- {ln}" for ln in weekday_text)
                parts.append("🕒 **Working Hours:**\n" + hours_md)
            parts.append("")

        return "\n".join(parts)

    # ───────────────────────── Prompt builder ─────────────────────────
    def _build_search_prompt(
        self,
        *,
        city: str,
        venue_type: str,
        audience: str,
        guest_count: Any,
        budget: Any,
        cuisine: str,
        weather_info: str,
        is_outdoor: bool = False,
    ) -> str:
        details = (
            f"\nParty Details:\n"
            f"- City: {city}\n"
            f"- Venue Type: {venue_type}\n"
            f"- Audience: {audience}\n"
            f"- Guests: {guest_count}\n"
            f"- Budget: {budget} ₺\n"
            f"- Cuisine: {cuisine}\n"
            f"- Weather Forecast: {weather_info}\n"
        )

        if is_outdoor:
            cuisine_line = "- Cuisine is optional for outdoor; prioritize parks, gardens, terraces, beach clubs, and other open-air venues.\n"
        else:
            cuisine_line = f"- Only suggest venues that primarily serve **{cuisine}** cuisine.\n" if cuisine else ""

        rules = (
            "\nIMPORTANT:\n"
            f"{cuisine_line}"
            "- If rainy/stormy: prioritize indoor/covered venues.\n"
            "- If clear/sunny: outdoor/hybrid are fine.\n"
            "- Suggest specific, real venues (names only). Keep description to one short sentence each.\n"
            "\nFormat:\n"
            "**Venue Name**: one short reason it fits the party and weather.\n"
        )

        if VENUE_SEARCH_PROMPT:
            return f"{VENUE_SEARCH_PROMPT.strip()}\n{details}{rules}"
        # Fallback inline prompt (if constants module not available)
        return (
            f"You are a venue expert for {city}, Turkey.\n"
            "Suggest 3 REAL venues that actually exist in the city.\n"
            f"{details}{rules}"
        )

    # ───────────────────────── Public entrypoint ─────────────────────────
    def process_request(self, ctx: Dict[str, Any]) -> Any:
        """
        Returns:
          {
            "suggestions": [PlaceDetails,...],
            "raw": "<llm raw or note>",
            "unified_display": "<markdown block>",
            "weather_info": "<string>"
          }
        """
        city = ctx.get("city", "")
        venue_type = ctx.get("location_type", "") or ctx.get("venue_type", "")
        audience = ctx.get("audience", "")
        guest_count = ctx.get("guest_count", "")
        budget = ctx.get("budget_venue", "")
        cuisine = ctx.get("cuisine", "")

        weather_info = self._get_weather_line(ctx)
        is_outdoor = _is_outdoor_type(venue_type)

        # For outdoor, do NOT force cuisine (treat as optional hint)
        cuisine_effective = "" if is_outdoor else cuisine

        prompt = self._build_search_prompt(
            city=city,
            venue_type=venue_type,
            audience=audience,
            guest_count=guest_count,
            budget=budget,
            cuisine=cuisine_effective,
            weather_info=weather_info,
            is_outdoor=is_outdoor,
        )

        # 1) Ask LLM for names (optional nicety; we’ll verify via Places)
        llm_response = self._call_llm_unified(prompt, ctx)

        # 2) Extract names, then resolve each to Place Details (ground truth)
        enriched: List[Dict[str, Any]] = []
        names: List[str] = self._extract_venue_names_from_text(llm_response) if llm_response else []

        if names:
            for n in names:
                det = self._search_venue_in_places(n, city, cuisine_effective)
                if det and (is_outdoor or not cuisine or self._matches_cuisine(det, cuisine)):
                    det["source"] = "google_places"
                    det["match_status"] = "found"
                    enriched.append(det)

        # 3) Fallback: cuisine-aware for indoor/hybrid, outdoor-friendly otherwise
        if not enriched:
            enriched = self._get_fallback_venues(
                city, venue_type, audience, cuisine_effective, is_outdoor=is_outdoor
            )
            for v in enriched:
                v["source"] = "fallback_search"
                v["match_status"] = "found"

        # 4) Final guard: if still empty and user had chosen a cuisine with outdoor,
        # try once more with cuisine totally relaxed (should rarely trigger)
        if not enriched and is_outdoor and cuisine:
            enriched = self._get_fallback_venues(city, venue_type, audience, "", is_outdoor=True)
            for v in enriched:
                v["source"] = "fallback_search"
                v["match_status"] = "found"

        # 5) Compose a friendly markdown block
        md = self._format_weather_and_venues(weather_info, enriched, city)

        return {
            "suggestions": enriched,
            "raw": llm_response or "No LLM response available",
            "unified_display": md,
            "weather_info": weather_info,
        }
