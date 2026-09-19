"""Fallback material-change analysis using dated ClientNotes.

The URO UI has a real last-consultation concept, but the supplied JSON export
we received does not expose that field.  Therefore the latest ClientNote date
is only a *proxy*.  Persistent state diffs should be preferred when available.
"""
from __future__ import annotations

from datetime import date, datetime
import math
from typing import Any, Optional

from .validation import INTERACTION_DATE_FIELDS


def _finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _parse_date(value: str) -> date:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).date()


def last_interaction_date(notes: list[dict]) -> Optional[date]:
    """Latest valid ClientNotes[].CreatedByDateUTC, or None."""
    dates: list[date] = []
    for note in notes or []:
        if not isinstance(note, dict) or not note.get("CreatedByDateUTC"):
            continue
        try:
            dates.append(_parse_date(note["CreatedByDateUTC"]))
        except (TypeError, ValueError):
            continue
    return max(dates) if dates else None


def resolve_interaction_date(client: dict) -> dict:
    """Prefer a genuine consultation/interaction field; fall back to ClientNotes."""
    for field in INTERACTION_DATE_FIELDS:
        value = client.get(field)
        if not value:
            continue
        try:
            return {
                "date": _parse_date(value),
                "source": field,
                "approximation": False,
            }
        except (TypeError, ValueError):
            continue

    notes = client.get("notes")
    if notes is None:
        notes = client.get("ClientNotes") or []
    d = last_interaction_date(notes)
    return {
        "date": d,
        "source": "client_note_proxy" if d is not None else None,
        "approximation": True if d is not None else None,
    }


def _usable_history(portfolio: dict) -> list[dict]:
    rows = []
    for h in portfolio.get("PerformanceHistory") or []:
        if not isinstance(h, dict) or not h.get("Date") or not _finite(h.get("Value")):
            continue
        try:
            d = _parse_date(h["Date"])
        except (TypeError, ValueError):
            continue
        rows.append({"date": d, "value": float(h["Value"])})
    rows.sort(key=lambda x: x["date"])
    return rows


def change_since_last_interaction(
    portfolio: dict,
    since: Optional[date],
    *,
    source: str = "client_note_proxy",
    approximation: bool = True,
) -> dict:
    """Portfolio-value change since the latest history point on/before ``since``.

    This is explicitly approximate. If the interaction proxy is *newer* than
    the latest available history point, the result is unavailable rather than
    the misleading 0.0 returned by the previous implementation.
    """
    history = _usable_history(portfolio)
    latest = history[-1] if history else None
    empty = {
        "status": "unavailable",
        "reason": None,
        "source": source,
        "approximation": approximation,
        "semantics": "portfolio_value_change_not_confirmed_return",
        "since_date": since.isoformat() if since else None,
        "value_then": None,
        "value_now": latest["value"] if latest else None,
        "change": None,
        "change_pct": None,
    }

    if since is None:
        return {**empty, "reason": "interaction_date_unavailable"}
    if not history:
        return {**empty, "reason": "performance_history_unavailable"}
    if since > latest["date"]:
        return {
            **empty,
            "reason": "interaction_after_latest_history_point",
            "latest_history_date": latest["date"].isoformat(),
        }

    points_before = [h for h in history if h["date"] <= since]
    if not points_before:
        return {**empty, "reason": "interaction_predates_available_history"}

    then = points_before[-1]
    change = latest["value"] - then["value"]
    change_pct = change / then["value"] if then["value"] else None
    return {
        "status": "partial",
        "reason": "client_note_used_as_interaction_proxy" if approximation else None,
        "source": source,
        "approximation": approximation,
        "semantics": "portfolio_value_change_not_confirmed_return",
        "since_date": since.isoformat(),
        "history_anchor_date": then["date"].isoformat(),
        "latest_history_date": latest["date"].isoformat(),
        "value_then": then["value"],
        "value_now": latest["value"],
        "change": change,
        "change_pct": change_pct,
    }
