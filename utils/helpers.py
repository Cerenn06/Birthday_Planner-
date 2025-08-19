from __future__ import annotations
from typing import Any, Dict, Iterable, Optional

def first_filled_str(res: Any, keys: Iterable[str]) -> Optional[str]:
    """
    If `res` is a string, return it (trimmed) if non-empty.
    If `res` is a dict, return the first non-empty string among the given keys.
    Otherwise return None.
    """
    if isinstance(res, str):
        s = res.strip()
        return s or None

    if isinstance(res, dict):
        for k in keys:
            v = res.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()
    return None


def pick_best_text(res: Any) -> Optional[str]:
    """
    Try hard to extract the most useful text from an agent response.
    Handles:
      - plain strings
      - nested dicts/lists containing strings
    Returns the longest non-empty string found (trimmed), or None.
    """
    if isinstance(res, str):
        s = res.strip()
        return s or None

    best = ""

    def visit(v: Any) -> None:
        nonlocal best
        if isinstance(v, str):
            s = v.strip()
            if len(s) > len(best):
                best = s
        elif isinstance(v, dict):
            for vv in v.values():
                visit(vv)
        elif isinstance(v, list):
            for vv in v:
                visit(vv)

    visit(res)
    return best or None


def ensure_markdown(text: Optional[str]) -> str:
    """Return a display-safe markdown string."""
    return text if (isinstance(text, str) and text.strip()) else "_no response_"


def safe_int(value: Any, default: int = 0) -> int:
    """Convert to int safely."""
    try:
        return int(str(value).strip())
    except Exception:
        return default


def coalesce_str(*vals: Any) -> Optional[str]:
    """Return the first non-empty string among vals."""
    for v in vals:
        if isinstance(v, str) and v.strip():
            return v.strip()
    return None
