from __future__ import annotations
from typing import List, Optional, TypedDict

class Budget(TypedDict, total=False):
    total: int
    venue: int
    menu: int
    activity: int

class EventRequest(TypedDict, total=False):
    
    location: str
    date: str           # e.g. "2025/08/12"

    # Guests
    guests: int         # e.g. 30
    audience: str       # e.g. "Kids"

    # Preferences
    venue_type: str     # e.g. "Indoor" | "Outdoor"
    cuisine: str        # e.g. "Turkish"
    dietary: List[str]  # e.g. ["Halal"]
    activity_type: str  # e.g. "Indoor" | "Outdoor" | "Mixed"

    # Budget
    budget: Budget

# Convenience: minimal factory to build a request dict from UI strings
def make_event_request(
    *,
    location: str,
    date: str,
    guests: int,
    venue_type: str,
    cuisine: str,
    audience: str,
    activity_type: str,
    dietary: List[str],
    total_budget: int,
    venue_budget: int,
    menu_budget: int,
    activity_budget: int,
) -> EventRequest:
    return EventRequest(
        location=location,
        date=date,
        guests=guests,
        audience=audience,
        venue_type=venue_type,
        cuisine=cuisine,
        dietary=list(dietary or []),
        activity_type=activity_type,
        budget=Budget(
            total=total_budget,
            venue=venue_budget,
            menu=menu_budget,
            activity=activity_budget,
        ),
    )
