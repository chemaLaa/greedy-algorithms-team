"""
Compares two portfolio state snapshots (previous vs. current, same
portfolio) and returns exactly what changed. This is the deterministic
answer to "what happened since we last looked at this client" — computed
from two small persisted summaries, not re-derived by guessing from raw
dates against the full transaction/performance history every time.
"""
from __future__ import annotations

from typing import Optional

# Allocation moves smaller than this (0.5 percentage points) are treated
# as noise and left out of the diff, rather than cluttering it with
# rounding-level drift nobody would call a "change".
ALLOCATION_CHANGE_EPSILON = 0.005


def diff_portfolio_snapshots(previous: Optional[dict], current: dict) -> dict:
    """
    `previous` is None when this portfolio has never been snapshotted
    before (a genuinely new client, or the first briefing ever generated
    for them) — the diff then reports everything in `current` as new
    rather than comparing against nothing.
    """
    if previous is None:
        return {
            "is_first_interaction": True,
            "since": None,
            "portfolio_value_change": None,
            "allocation_changes": {},
            "violations_new": current["violations"],
            "violations_resolved": [],
            "position_changes": {"entered_top": current["top_positions"], "exited_top": []},
        }

    value_change = _value_change(previous.get("portfolio_value"), current.get("portfolio_value"))
    allocation_changes = _allocation_changes(
        previous.get("allocation") or {}, current.get("allocation") or {}
    )
    violations_new, violations_resolved = _violation_changes(
        previous.get("violations") or [], current.get("violations") or []
    )
    position_changes = _position_changes(
        previous.get("top_positions") or [], current.get("top_positions") or []
    )

    return {
        "is_first_interaction": False,
        "since": previous.get("captured_at"),
        "portfolio_value_change": value_change,
        "allocation_changes": allocation_changes,
        "violations_new": violations_new,
        "violations_resolved": violations_resolved,
        "position_changes": position_changes,
    }


def _value_change(then, now) -> Optional[dict]:
    if then is None or now is None:
        return None
    change = now - then
    return {
        "then": then,
        "now": now,
        "change": change,
        "change_pct": (change / then) if then else None,
    }


def _allocation_changes(previous_alloc: dict, current_alloc: dict) -> dict:
    result = {}
    for dimension in set(previous_alloc) | set(current_alloc):
        prev_categories = previous_alloc.get(dimension, {})
        curr_categories = current_alloc.get(dimension, {})
        dim_changes = {}
        for category in set(prev_categories) | set(curr_categories):
            then_w = prev_categories.get(category, 0.0)
            now_w = curr_categories.get(category, 0.0)
            delta = now_w - then_w
            if abs(delta) >= ALLOCATION_CHANGE_EPSILON:
                dim_changes[category] = {"then": then_w, "now": now_w, "change": delta}
        if dim_changes:
            result[dimension] = dim_changes
    return result


def _violation_changes(previous_codes: list, current_codes: list) -> tuple[list, list]:
    prev_set, curr_set = set(previous_codes), set(current_codes)
    return sorted(curr_set - prev_set), sorted(prev_set - curr_set)


def _position_changes(previous_positions: list, current_positions: list) -> dict:
    prev_ids = {p["SecurityId"] for p in previous_positions}
    curr_ids = {p["SecurityId"] for p in current_positions}
    return {
        "entered_top": [p for p in current_positions if p["SecurityId"] not in prev_ids],
        "exited_top": [p for p in previous_positions if p["SecurityId"] not in curr_ids],
    }
