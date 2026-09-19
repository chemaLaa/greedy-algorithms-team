"""
state/counterfactual.py
───────────────────────
Pattern-history lookup: has a given signal type appeared in this client's
past state diffs? Uses the rolling event log already persisted by
state/store.py rather than re-scanning raw snapshots.

Events in the log are strings with the format:
    "<ISO8601_timestamp>: <description>"
e.g.:
    "2026-09-01T10:00:00+00:00: new violation — RULE_CODE"
    "2026-09-01T10:00:00+00:00: portfolio value up 8.3%"
    "2026-09-01T10:00:00+00:00: Nestle SA entered top positions (12.5%)"

Each SIGNAL_TYPE maps to a substring pattern that identifies matching events.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from .store import load_client_state

SIGNAL_TYPES = [
    "violation_new",
    "saa_breach",
    "concentration",
    "liquidity",
    "position_entered_top",
    "position_exited_top",
]

# Maps each signal type to a regex pattern that matches the description part
# (everything after the first ": ") of an event string.
_SIGNAL_PATTERNS: dict[str, re.Pattern] = {
    "violation_new":       re.compile(r"new violation\s*—"),
    "saa_breach":          re.compile(r"saa breach|saa_breach", re.IGNORECASE),
    "concentration":       re.compile(r"concentration", re.IGNORECASE),
    "liquidity":           re.compile(r"liquidity", re.IGNORECASE),
    "position_entered_top": re.compile(r"entered top positions"),
    "position_exited_top":  re.compile(r"dropped out of top positions"),
}

# Regex to extract the timestamp from an event string (everything before ": ").
_TIMESTAMP_RE = re.compile(r"^(\S+):\s")

# Regex to extract a portfolio value change percentage from an event string.
# e.g. "portfolio value up 8.3%" or "portfolio value down 12.5%"
_VALUE_CHANGE_RE = re.compile(
    r"portfolio value\s+(up|down)\s+([\d.]+)%", re.IGNORECASE
)


def _parse_event(event_str: str) -> Optional[dict]:
    """
    Parse an event string into a dict with 'date' and 'description'.
    Returns None if the string doesn't match the expected format.
    """
    m = _TIMESTAMP_RE.match(event_str)
    if not m:
        return None
    date = m.group(1)
    description = event_str[m.end():]
    return {"date": date, "description": description, "raw": event_str}


def _matches_signal(event: dict, signal_type: str) -> bool:
    """True if this event's description matches the given signal_type pattern."""
    pattern = _SIGNAL_PATTERNS.get(signal_type)
    if pattern is None:
        return False
    return bool(pattern.search(event["description"]))


def _portfolio_value_change_after(events: list[dict], match_index: int) -> Optional[float]:
    """
    Looks at the event immediately following `match_index` for a
    portfolio value change. Returns the signed change as a float (e.g.
    0.083 for "up 8.3%", -0.125 for "down 12.5%"), or None if no such
    event follows or the next event doesn't carry a value change.
    """
    if match_index + 1 >= len(events):
        return None
    next_event = events[match_index + 1]
    m = _VALUE_CHANGE_RE.search(next_event["description"])
    if not m:
        return None
    direction = m.group(1).lower()
    magnitude = float(m.group(2)) / 100.0
    return magnitude if direction == "up" else -magnitude


def check_pattern_history(
    client_ref: str,
    signal_type: str,
    state_dir: Path = Path(".state"),
) -> dict:
    """
    Looks up whether a given signal type has appeared in this client's
    rolling event log (persisted by state/store.py).

    Parameters
    ----------
    client_ref : str
        The client reference string, matching what was used in
        refresh_client_state() (typically the client's ClientId as a string).
    signal_type : str
        One of SIGNAL_TYPES. Raises ValueError if not recognised.
    state_dir : Path
        Directory where client state files are stored. Defaults to ".state".

    Returns
    -------
    dict with keys:
        occurred_before : bool
        occurrences : int
        total_snapshots_checked : int
        sample : list of {"date": str, "chf_change_after": float | None}
            (up to 3 entries)
    """
    if signal_type not in SIGNAL_TYPES:
        raise ValueError(
            f"Unknown signal_type {signal_type!r}. Must be one of: {SIGNAL_TYPES}"
        )

    stored = load_client_state(client_ref, state_dir)

    # No file found → empty state returned by load_client_state
    snapshots = stored.get("snapshots") or {}
    raw_events = stored.get("events") or []

    total_snapshots = len(snapshots)

    if not raw_events:
        return {
            "occurred_before": False,
            "occurrences": 0,
            "total_snapshots_checked": total_snapshots,
            "sample": [],
        }

    # Parse all events
    parsed_events = [e for e in (_parse_event(s) for s in raw_events) if e is not None]

    # Find matches
    matches: list[tuple[dict, Optional[float]]] = []
    for idx, event in enumerate(parsed_events):
        if _matches_signal(event, signal_type):
            chf_change = _portfolio_value_change_after(parsed_events, idx)
            matches.append((event, chf_change))

    return {
        "occurred_before": len(matches) > 0,
        "occurrences": len(matches),
        "total_snapshots_checked": total_snapshots,
        "sample": [
            {"date": e["date"], "chf_change_after": chf_change}
            for e, chf_change in matches[:3]
        ],
    }
