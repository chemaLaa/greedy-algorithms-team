"""
"What changed since the last client interaction" — one of the required
briefing inputs (DATA.md / case brief: "material changes since the
previous client interaction"). The schema has no explicit
"last interaction date" field and no position-level history, only
portfolio-level monthly NAV (PerformanceHistory) and free-text
ClientNotes with dates — so this module uses the most recent note's date
as a proxy for "last interaction" and measures portfolio value change
since then. This is an explicit, documented approximation, not something
the schema states directly — flagged here rather than silently assumed.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional


def _parse_date(value: str) -> date:
    # Handles both "yyyy-MM-dd" and full ISO datetime strings.
    return datetime.fromisoformat(value.replace("Z", "+00:00")).date()


def last_interaction_date(notes: list[dict]) -> Optional[date]:
    """
    Latest ClientNotes[].CreatedByDateUTC, or None if there are no notes.
    Remember: per DATA.md, dates across the export are shifted by a
    constant offset, so this is only meaningful as a relative anchor
    (e.g. "since this note"), never as a real calendar date.
    """
    dates = [_parse_date(n["CreatedByDateUTC"]) for n in notes if n.get("CreatedByDateUTC")]
    return max(dates) if dates else None


def change_since_last_interaction(portfolio: dict, since: Optional[date]) -> dict:
    """
    Portfolio value change from the latest PerformanceHistory point
    on-or-before `since` to the most recent point overall. All fields are
    None if `since` is unknown, there's no history, or no history point
    falls on/before `since` (e.g. the last interaction predates all
    recorded history).
    """
    history = portfolio.get("PerformanceHistory") or []
    empty = {
        "since_date": since,
        "value_then": None,
        "value_now": history[-1]["Value"] if history else None,
        "change": None,
        "change_pct": None,
    }
    if since is None or not history:
        return empty

    points_before = [h for h in history if _parse_date(h["Date"]) <= since]
    if not points_before:
        return empty

    then, now = points_before[-1], history[-1]
    change = now["Value"] - then["Value"]
    change_pct = (change / then["Value"]) if then["Value"] else None

    return {
        "since_date": since,
        "value_then": then["Value"],
        "value_now": now["Value"],
        "change": change,
        "change_pct": change_pct,
    }
