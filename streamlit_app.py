# streamlit_app.py
from __future__ import annotations

import os
from pathlib import Path
from datetime import date
from typing import Any, Dict, List
import json
from io import BytesIO

import streamlit as st

# ───────────────────────── .env LOAD ─────────────────────────
try:
    from dotenv import load_dotenv  # type: ignore
    _ENV_LOADED = load_dotenv(Path(__file__).resolve().parent / ".env", override=True)
except Exception:
    _ENV_LOADED = False

GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
GOOGLE_MAPS_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY")

# ───────────────────────── Output limits (hidden defaults) ─────────────────────────
DEFAULT_MAX_BULLETS = 15
DEFAULT_MAX_CHARS = 0  

# Enums / choices
VenueTypeStr = ["Indoor", "Outdoor", "Hybrid"]
AgeGroupStr = ["Kids", "Teenager", "Adult"]
CuisineStr = ["Turkish", "Italian", "Mixed", "Mediterranean", "Asian", "International"]
DietaryStr = ["Halal", "Vegetarian", "Vegan", "Gluten-free", "Nut-free"]
ActivityTypeStr = ["Indoor", "Outdoor", "Mixed"]

try:
    from b_types.birthday_types import VenueType, AgeGroup  # type: ignore
    VenueTypeStr = [v.value.capitalize() for v in VenueType]  # type: ignore
    AgeGroupStr = [a.value.capitalize() for a in AgeGroup]    # type: ignore
except Exception:
    pass

# Weather helper
try:
    from utils.weather_api import get_forecast_for_date  # type: ignore
except Exception:
    from weather_api import get_forecast_for_date  # fallback

# ───────────────────────── Agents ─────────────────────────
@st.cache_resource(show_spinner=False)
def get_agents():
    from agents.budget_agent import BudgetAgent
    from agents.venue_agent import VenueAgent
    from agents.menu_agent import MenuAgent
    from agents.activity_agent import ActivityAgent
    from agents.guest_agent import GuestAgent

    return {
        "Budget": BudgetAgent(),
        "Venue": VenueAgent(),
        "Menu": MenuAgent(),
        "Activity": ActivityAgent(),
        "Guest": GuestAgent(),
    }

def run_agent_safe(agent, ctx: Dict[str, Any]) -> Any:
    try:
        if hasattr(agent, "process_request"):
            return agent.process_request(ctx)
        return "Agent does not implement process_request."
    except Exception as e:
        return f"❌ Exception from {agent.__class__.__name__}: {e}"

# ───────────────────────── UI: Inputs ─────────────────────────
st.set_page_config(page_title="Birthday Planner", page_icon="🎉", layout="centered")
st.title("🎉 Birthday Planner")

with st.form("planner_form", clear_on_submit=False):
    st.subheader("Event basics")
    col_city, col_date, col_guests = st.columns([1.3, 1, 1])
    with col_city:
        city = st.text_input("City", value="Ankara")
    with col_date:
        party_date: date = st.date_input("Date", value=date.today())
    with col_guests:
        guest_count = st.number_input("Guests", min_value=1, max_value=300, value=20, step=1)

    st.subheader("Preferences")
    col_vt, col_aud, col_cui = st.columns(3)
    with col_vt:
        venue_type = st.selectbox("Venue type", VenueTypeStr, index=0)
    with col_aud:
        audience = st.selectbox("Audience", AgeGroupStr, index=0)
    with col_cui:
        cuisine = st.selectbox("Cuisine", CuisineStr, index=2)

    dietary = st.multiselect("Dietary restrictions (optional)", DietaryStr, default=["Halal"])
    activity_type = st.selectbox("Activity type", ActivityTypeStr, index=0)

    st.subheader("Budget")
    col_tot, col_v, col_m, col_act = st.columns(4)
    with col_tot:
        budget_total = st.number_input("Total budget (₺)", min_value=0, value=3000, step=100)
    with col_v:
        budget_venue = st.number_input("Venue (₺)", min_value=0, value=1200, step=100)
    with col_m:
        budget_menu = st.number_input("Menu (₺)", min_value=0, value=1200, step=100)
    with col_act:
        budget_activity = st.number_input("Activity (₺)", min_value=0, value=600, step=100)

    submitted = st.form_submit_button("Generate Plan 🚀", type="primary")

# ───────────────────────── Render helpers ─────────────────────────
def _first_n_bullets(md: str, n: int, plain_char_limit: int = 0) -> str:
    lines = md.splitlines()
    bullets, rest = [], []
    bullet_prefixes = ("- ", "* ", "• ", "1. ", "2. ", "3. ")
    count = 0
    for ln in lines:
        if ln.strip().startswith(bullet_prefixes) and count < n:
            bullets.append(ln)
            count += 1
        elif ln.strip().startswith(bullet_prefixes) and count >= n:
            continue
        else:
            rest.append(ln)

    plain = "\n".join(rest).strip()

    
    if plain_char_limit and len(plain) > plain_char_limit:
        cut = plain[:plain_char_limit]
        last_break = max(cut.rfind("\n"), cut.rfind(". "), cut.rfind("! "), cut.rfind("? "))
        if last_break > 100:
            plain = cut[:last_break+1].rstrip() + "…"
        else:
            plain = cut.rstrip() + "…"

    parts = [plain] if plain else []
    if bullets:
        parts.append("\n".join(bullets))
    return "\n\n".join(parts).strip()

def _enforce_limits(payload: Any, max_bullets: int = DEFAULT_MAX_BULLETS, max_chars: int = DEFAULT_MAX_CHARS) -> Any:
    if isinstance(payload, str):
        text = _first_n_bullets(payload, max_bullets, plain_char_limit=(max_chars or 0))
        if max_chars and len(text) > max_chars:
            cut = text[:max_chars]
            last_break = max(cut.rfind("\n"), cut.rfind(". "), cut.rfind("! "), cut.rfind("? "))
            if last_break > 100:
                text = cut[:last_break+1].rstrip() + "…"
            else:
                text = cut.rstrip() + "…"
        return text
    if isinstance(payload, list):
        return payload[:max_bullets] + (["…"] if len(payload) > max_bullets else [])
    if isinstance(payload, dict):
        return payload
    return payload  # fallback

# --------
def _as_inline_text(v: Any) -> str:
    if isinstance(v, list):
        return ", ".join([_as_inline_text(x) for x in v])
    if isinstance(v, dict):
        parts = []
        for k, vv in v.items():
            parts.append(f"{k}: {_as_inline_text(vv)}")
        return "; ".join(parts)
    return str(v).strip()

def _dict_to_markdown(d: Any) -> str:
    """Dict outputs should be short, convert them into a conversational Markdown style."""
    if not isinstance(d, dict):
        return str(d)
    
    if len(d) == 1 and "menu" in d and isinstance(d["menu"], dict):
        d = d["menu"]
    lines: List[str] = []
    for k, v in d.items():
        if isinstance(v, dict):
            lines.append(f"**{k}**")
            for sk, sv in v.items():
                lines.append(f"- **{sk}:** {_as_inline_text(sv)}")
        else:
            lines.append(f"- **{k}:** {_as_inline_text(v)}")
    return "\n".join(lines).strip()

def _maybe_json_to_markdown(s: str) -> str:
    """If a string looks like JSON, parse it and convert it into Markdown; otherwise, return it as is."""
    if not isinstance(s, str):
        return str(s)
    s_stripped = s.strip()
    if s_stripped.startswith("{") or s_stripped.startswith("["):
        try:
            data = json.loads(s_stripped)
            if isinstance(data, dict):
                return _dict_to_markdown(data)
            if isinstance(data, list):
                return "\n".join(f"- {_as_inline_text(x)}" for x in data)
        except Exception:
            pass
    return s

def _to_human_text(payload: Any) -> str:
    """Convert any type of payload (dict/list/str) into a readable, concise text."""
    if isinstance(payload, dict):
        return _dict_to_markdown(payload)
    if isinstance(payload, list):
        return "\n".join(f"- {_as_inline_text(x)}" for x in payload)
    if isinstance(payload, str):
        return _maybe_json_to_markdown(payload)
    return _payload_to_text(payload)

# ---- City Filter ----
def _filter_suggestions_by_city(suggestions: List[Dict[str, Any]], city_name: str) -> List[Dict[str, Any]]:
    goal = (city_name or "").casefold()
    if not goal:
        return suggestions
    keep: List[Dict[str, Any]] = []
    for v in suggestions:
        addr = (v.get("formatted_address") or v.get("vicinity") or "").casefold()
        name = (v.get("name") or "").casefold()
        
        if goal in addr or goal in name:
            keep.append(v)
    
    return keep or suggestions

def render_output(title: str, payload: Any):
    with st.expander(title, expanded=True):
        if payload is None:
            st.info("No output.")
        elif isinstance(payload, str):
            md = _maybe_json_to_markdown(payload)
            md = _enforce_limits(md, max_bullets=DEFAULT_MAX_BULLETS, max_chars=0)
            st.markdown(md)
        elif isinstance(payload, dict):
            md = _dict_to_markdown(payload)
            md = _enforce_limits(md, max_bullets=DEFAULT_MAX_BULLETS, max_chars=0)
            st.markdown(md)
        elif isinstance(payload, (list, tuple)):
            for i, item in enumerate(payload, 1):
                st.markdown(f"**{i}.**")
                if isinstance(item, dict):
                    md = _dict_to_markdown(item)
                    md = _enforce_limits(md, max_bullets=DEFAULT_MAX_BULLETS, max_chars=0)
                    st.markdown(md)
                else:
                    st.write(item)
        else:
            st.write(payload)

def render_venue_with_weather(venue_result, current_city: str | None = None):
    """Render venue results with unified weather and venue information."""
    if isinstance(venue_result, str):
        st.error(venue_result)
        return

    if isinstance(venue_result, dict):
        unified_display = venue_result.get("unified_display")
        if unified_display:
            st.markdown(unified_display)
            return

        suggestions = venue_result.get("suggestions", []) or []
        if current_city:
            suggestions = _filter_suggestions_by_city(suggestions, current_city)

        weather_info = venue_result.get("weather_info") or venue_result.get("weather_forecast_text", "")
        if weather_info and "not available" not in weather_info.lower():
            st.info(f"🌤️ **Weather Forecast:** {weather_info}")
        
        raw_text = (venue_result.get("raw") or "").strip()
        if raw_text:
            st.markdown("**Overview**")
            st.markdown(_enforce_limits(raw_text, max_bullets=DEFAULT_MAX_BULLETS, max_chars=0))

        if suggestions:
            st.markdown("**🏟️ Recommended Venues:**")
            render_enhanced_venue_cards(suggestions)
        else:
            st.warning("No venues found. Please try different search criteria.")
    else:
        st.write(venue_result)

def render_enhanced_venue_cards(suggestions):
    if not suggestions:
        st.info("No venues found.")
        return

    for i, venue in enumerate(suggestions, 1):
        with st.container(border=True):
            name = venue.get("name", "Unknown Venue")
            st.markdown(f"### {i}. {name}")

            address = venue.get("formatted_address", "Address not available")
            st.markdown(f"📍 **Address:** {address}")

            col1, col2 = st.columns([1, 1])
            with col1:
                rating = venue.get("rating")
                user_ratings = venue.get("user_ratings_total")
                if rating:
                    stars = "⭐" * int(round(rating))
                    st.markdown(f"**Rating:** {stars} {rating}/5")
                    if user_ratings:
                        st.caption(f"({user_ratings} reviews)")

                phone = venue.get("formatted_phone_number") or venue.get("international_phone_number")
                if phone:
                    st.markdown(f"📞 **Phone:** {phone}")

            with col2:
                price_level = venue.get("price_level")
                if price_level is not None:
                    price_symbols = "₺" * (int(price_level) + 1)
                    st.markdown(f"💰 **Price Level:** {price_symbols}")

                website = venue.get("website")
                if website:
                    st.markdown(f"🌐 [Website]({website})")

            hours = venue.get("opening_hours", {})
            if isinstance(hours, dict) and hours.get("weekday_text"):
                with st.expander("Opening Hours"):
                    for day_hours in hours.get("weekday_text", []):
                        st.write(day_hours)

            col_maps, col_web, col_status = st.columns([1, 1, 2])
            with col_maps:
                maps_url = venue.get("maps_url")
                place_id = venue.get("place_id")
                try:
                    st.link_button(
                        "🗺️ Open in Maps",
                        maps_url or (f"https://www.google.com/maps/place/?q=place_id:{place_id}" if place_id else "#"),
                        use_container_width=True,
                    )
                except Exception:
                    if maps_url:
                        st.markdown(f"[🗺️ Open in Maps]({maps_url})")
                    elif place_id:
                        st.markdown(f"[🗺️ Open in Maps](https://www.google.com/maps/place/?q=place_id:{place_id})")

            with col_web:
                website = venue.get("website")
                if website:
                    try:
                        st.link_button("🌐 Visit Website", website, use_container_width=True)
                    except Exception:
                        st.markdown(f"[🌐 Visit Website]({website})")

            with col_status:
                status = venue.get("match_status", "unknown")
                source = venue.get("source", "unknown")
                if status == "found":
                    st.success(f"✅ Verified from {source}")
                elif status == "not_verified":
                    st.warning("⚠️ Please verify details")
                else:
                    st.info(f"ℹ️ Status: {status}")

            note = venue.get("note")
            if note:
                st.info(f"💡 **Note:** {note}")

# ───────────────────────── Export helpers (PDF) ─────────────────────────
def _normalize_tr_ascii(s: str) -> str:
    if not isinstance(s, str):
        return ""
    s = s.strip()  # <<< IMPORTANT: trim whitespace
    table = str.maketrans({
        "ı": "i", "İ": "I", "ş": "s", "Ş": "S", "ğ": "g", "Ğ": "G",
        "ü": "u", "Ü": "U", "ö": "o", "Ö": "O", "ç": "c", "Ç": "C",
    })
    try:
        return s.translate(table).encode("ascii", "ignore").decode("ascii")
    except Exception:
        return s

def _payload_to_text(payload: Any) -> str:
    try:
        if payload is None:
            return "No data."
        if isinstance(payload, str):
            return payload
        if isinstance(payload, dict):
            return json.dumps(payload, ensure_ascii=False, indent=2)
        if isinstance(payload, (list, tuple)):
            return "\n".join(
                (json.dumps(x, ensure_ascii=False, indent=2) if isinstance(x, dict) else str(x))
                for x in payload
            )
        return str(payload)
    except Exception:
        return str(payload)

def _build_pdf_bytes(plan_title: str, meta: Dict[str, str], sections: Dict[str, str]) -> bytes:
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
    except Exception:
        return b"%PDF-1.4\n1 0 obj <<>> endobj\ntrailer <<>>\n%%EOF\n"

    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=36, rightMargin=36, topMargin=36, bottomMargin=36,
        title=plan_title,
    )
    styles = getSampleStyleSheet()
    has_unicode_font = False

    try:
        font_path_candidates = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/local/share/fonts/DejaVuSans.ttf",
            str(Path(__file__).resolve().parent / "DejaVuSans.ttf"),
        ]
        font_path = next((p for p in font_path_candidates if os.path.exists(p)), None)
        if font_path:
            pdfmetrics.registerFont(TTFont("DejaVuSans", font_path))
            styles["Normal"].fontName = "DejaVuSans"
            styles["Heading1"].fontName = "DejaVuSans"
            styles["Heading2"].fontName = "DejaVuSans"
            styles["Heading3"].fontName = "DejaVuSans"
            has_unicode_font = True
    except Exception:
        has_unicode_font = False

    def _txt(s: str) -> str:
        return s if has_unicode_font else _normalize_tr_ascii(s)

    story: List[Any] = []
    story.append(Paragraph(_txt(plan_title), styles["Heading1"]))
    story.append(Spacer(1, 8))

    meta_lines = []
    for k in ["City", "Date", "Weather"]:
        if k in meta and meta[k]:
            meta_lines.append(f"<b>{k}:</b> {_txt(meta[k])}")
    if meta_lines:
        story.append(Paragraph("<br/>".join(meta_lines), styles["Normal"]))
    story.append(Spacer(1, 12))

    for sec_title, sec_text in sections.items():
        story.append(Paragraph(_txt(sec_title), styles["Heading2"]))
        story.append(Spacer(1, 6))
        safe_text = _txt(sec_text).replace("\n", "<br/>")
        story.append(Paragraph(safe_text, styles["Normal"]))
        story.append(Spacer(1, 12))

    try:
        doc.build(story)
        return buf.getvalue()
    except Exception:
        return b"%PDF-1.4\n1 0 obj <<>> endobj\ntrailer <<>>\n%%EOF\n"

# ───────────────────────── Main Action ─────────────────────────
if submitted:
    agents = get_agents()

    ctx: Dict[str, Any] = {
        "location": city,
        "city": city,
        "date": party_date.isoformat(),
        "event_date": party_date.isoformat(),
        "guests": int(guest_count),
        "guest_count": int(guest_count),
        "audience": audience,
        "venue_type": venue_type,
        "location_type": venue_type,
        "cuisine": cuisine,
        "dietary": list(dietary),
        "diet_restrictions": list(dietary),
        "activity_type": activity_type,
        "activity_location": activity_type,
        "budget": {
            "total": int(budget_total),
            "venue": int(budget_venue),
            "menu": int(budget_menu),
            "activity": int(budget_activity),
        },
        "budget_total": int(budget_total),
        "budget_venue": int(budget_venue),
        "budget_food": int(budget_menu),
        "budget_activity": int(budget_activity),
        "google_maps_api_key": GOOGLE_MAPS_API_KEY,
        "search_radius_m": 5000,
        "style": {
            "concise": True,
            "max_bullets": DEFAULT_MAX_BULLETS,
            "language": "en",
            "no_redundant_context": True,
        },
    }

    # Weather
    st.info("Fetching weather forecast...")
    try:
        fx = get_forecast_for_date(
            city=city,
            when=party_date,
            maps_api_key=GOOGLE_MAPS_API_KEY,
            target_hour_local=18,
        )

        if fx:
            def _fmt(v):
                try:
                    return f"{float(v):.0f}"
                except Exception:
                    return "—"
            parts: List[str] = []
            emoji = fx.get("weather_emoji", "")
            text = fx.get("weather_text", "")
            if emoji:
                parts.append(emoji)
            if text:
                parts.append(text)
            texp = fx.get("t_expected_c")
            tmin = fx.get("t_min_c")
            tmax = fx.get("t_max_c")
            if texp is not None:
                parts.append(f"{_fmt(texp)}°C")
            if (tmin is not None) and (tmax is not None):
                parts.append(f"({_fmt(tmin)}°C - {_fmt(tmax)}°C)")
            ctx["weather_forecast_text"] = " ".join(parts).strip() or "Weather forecast unavailable"
            ctx["weather_forecast"] = fx
            st.success(f"Weather: {ctx['weather_forecast_text']}")
        else:
            ctx["weather_forecast_text"] = "Weather forecast unavailable - please check local conditions"
            ctx["weather_forecast"] = {}
            st.warning("Could not fetch weather forecast")
    except Exception as e:
        ctx["weather_forecast_text"] = f"Weather fetch error: {e}"
        ctx["weather_forecast"] = {}
        st.error(f"Weather error: {e}")

    # Run agents
    st.info("Generating recommendations...")
    with st.spinner("Processing..."):
        r_budget = run_agent_safe(agents["Budget"], ctx)
        r_venue = run_agent_safe(agents["Venue"], ctx)
        r_menu = run_agent_safe(agents["Menu"], ctx)
        r_activity = run_agent_safe(agents["Activity"], ctx)
        r_guest = run_agent_safe(agents["Guest"], ctx)

    # Enforce limits 
    r_budget   = _enforce_limits(r_budget, max_bullets=10, max_chars=0)
    r_venue    = _enforce_limits(r_venue,  max_bullets=10, max_chars=0)
    r_menu     = _enforce_limits(r_menu,   max_bullets=10, max_chars=0)
    r_activity = _enforce_limits(r_activity, max_bullets=10, max_chars=1200)  
    r_guest    = _enforce_limits(r_guest,  max_bullets=10, max_chars=0)

    st.success("✅ All recommendations generated!")

    tabs = st.tabs(["🏟️ Venue", "🍽️ Menu", "🎯 Activities", "👥 Guests"])

    with tabs[0]:
        st.caption(f"City: **{city}** • Date: **{party_date.isoformat()}**")
        render_venue_with_weather(r_venue, current_city=city)

    with tabs[1]:
        render_output("Menu", r_menu)

    with tabs[2]:
        render_output("Activities", r_activity)

    with tabs[3]:
        render_output("Guests", r_guest)

    # ───────────────────────── Export: Download PDF ─────────────────────────
    st.divider()
    st.subheader("Export")

    venue_text = ""
    if isinstance(r_venue, dict):
        venue_text = r_venue.get("unified_display") or _payload_to_text(r_venue.get("suggestions"))
        if not venue_text:
            venue_text = _payload_to_text(r_venue)
    else:
        venue_text = _payload_to_text(r_venue)

    
    menu_md     = _to_human_text(r_menu)
    activity_md = _to_human_text(r_activity)
    guests_md   = _to_human_text(r_guest)

    sections = {
        "Venue":      _enforce_limits(venue_text,  max_bullets=10, max_chars=0),
        "Menu":       _enforce_limits(menu_md,     max_bullets=10, max_chars=0),
        "Activities": _enforce_limits(activity_md, max_bullets=10, max_chars=900),
        "Guests":     _enforce_limits(guests_md,   max_bullets=10, max_chars=0),
    }
    meta = {
        "City": city,
        "Date": party_date.isoformat(),
        "Weather": ctx.get("weather_forecast_text", ""),
    }
    pdf_bytes = _build_pdf_bytes(
        plan_title=f"Birthday Plan - {city} - {party_date.isoformat()}",
        meta=meta,
        sections=sections,
    )

    st.download_button(
        label="⬇️ Download plan as PDF",
        data=pdf_bytes,
        file_name=f"birthday_plan_{city}_{party_date.isoformat()}.pdf",
        mime="application/pdf",
        use_container_width=True,
    )

    # Debug
    st.divider()
    with st.expander("🔍 Debug Information"):
        st.json({
            "city": city,
            "date": party_date.isoformat(),
            "guest_count": guest_count,
            "venue_type": venue_type,
            "audience": audience,
            "cuisine": cuisine,
            "dietary": dietary,
            "activity_type": activity_type,
            "weather_info": ctx.get("weather_forecast_text", "No weather data"),
            "google_maps_key_available": bool(GOOGLE_MAPS_API_KEY),
            "google_api_key_available": bool(GOOGLE_API_KEY),
        })

else:
    st.info("👆 Fill in the details above, then click **Generate Plan 🚀** to get started!")
