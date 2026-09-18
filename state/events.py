"""
Turns one diff into a short list of human-readable event strings, and the
refresh orchestrator appends these to a rolling per-client log capped at
MAX_EVENTS entries — the "important_historical_events" longer-range
context across many past interactions, not just the most recent diff.
"""
from __future__ import annotations

# A portfolio-value move smaller than this is routine noise, not an event
# worth remembering months from now.
NOTABLE_VALUE_CHANGE_PCT = 0.05


def summarize_diff_as_events(diff: dict, captured_at: str) -> list[str]:
    if diff.get("is_first_interaction"):
        return [f"{captured_at}: first briefing generated for this client"]

    events = []

    for code in diff.get("violations_new", []):
        events.append(f"{captured_at}: new violation — {code}")
    for code in diff.get("violations_resolved", []):
        events.append(f"{captured_at}: violation resolved — {code}")

    value_change = diff.get("portfolio_value_change")
    if value_change and value_change.get("change_pct") is not None:
        pct = value_change["change_pct"]
        if abs(pct) >= NOTABLE_VALUE_CHANGE_PCT:
            direction = "up" if pct > 0 else "down"
            events.append(f"{captured_at}: portfolio value {direction} {abs(pct):.1%}")

    position_changes = diff.get("position_changes") or {}
    for pos in position_changes.get("entered_top", []):
        weight = pos.get("weight")
        weight_str = f" ({weight:.1%})" if weight is not None else ""
        events.append(f"{captured_at}: {pos['SecurityName']} entered top positions{weight_str}")
    for pos in position_changes.get("exited_top", []):
        events.append(f"{captured_at}: {pos['SecurityName']} dropped out of top positions")

    return events
