"""
Tests for state/counterfactual.py:
  - No state file → all zeros, occurred_before=False
  - State file with one matching event and a following value-change event
    → occurred_before=True, chf_change_after populated
  - State file with one matching event and NO following event
    → chf_change_after=None
  - Unknown signal_type → ValueError
"""
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from state.counterfactual import check_pattern_history, SIGNAL_TYPES


def _write_state(state_dir: Path, client_ref: str, snapshots: dict, events: list[str]):
    """Write a fake state file for testing."""
    state_dir.mkdir(parents=True, exist_ok=True)
    path = state_dir / f"{client_ref}.json"
    with open(path, "w") as f:
        json.dump({"snapshots": snapshots, "events": events}, f)


# ---------------------------------------------------------------------------
# No state file → all zeros
# ---------------------------------------------------------------------------

def test_no_state_file_returns_all_zeros():
    with tempfile.TemporaryDirectory() as tmpdir:
        result = check_pattern_history(
            client_ref="nonexistent_client",
            signal_type="violation_new",
            state_dir=Path(tmpdir),
        )
    assert result["occurred_before"] is False
    assert result["occurrences"] == 0
    assert result["total_snapshots_checked"] == 0
    assert result["sample"] == []


# ---------------------------------------------------------------------------
# Matching event with a following value-change event
# ---------------------------------------------------------------------------

def test_matching_event_with_following_value_change():
    events = [
        "2026-09-01T10:00:00+00:00: new violation — RULE_001",
        "2026-09-02T10:00:00+00:00: portfolio value down 8.3%",
    ]
    snapshots = {"9001": {"portfolio_value": 500000}}

    with tempfile.TemporaryDirectory() as tmpdir:
        state_dir = Path(tmpdir)
        _write_state(state_dir, "client1", snapshots, events)

        result = check_pattern_history(
            client_ref="client1",
            signal_type="violation_new",
            state_dir=state_dir,
        )

    assert result["occurred_before"] is True
    assert result["occurrences"] == 1
    assert result["total_snapshots_checked"] == 1
    assert len(result["sample"]) == 1
    assert result["sample"][0]["date"] == "2026-09-01T10:00:00+00:00"
    # -8.3% expressed as fraction
    assert abs(result["sample"][0]["chf_change_after"] - (-0.083)) < 1e-9


def test_matching_event_with_following_value_change_up():
    events = [
        "2026-09-01T10:00:00+00:00: new violation — RULE_001",
        "2026-09-02T10:00:00+00:00: portfolio value up 5.0%",
    ]
    with tempfile.TemporaryDirectory() as tmpdir:
        state_dir = Path(tmpdir)
        _write_state(state_dir, "client1", {}, events)

        result = check_pattern_history("client1", "violation_new", state_dir)

    assert result["sample"][0]["chf_change_after"] == pytest.approx(0.05, rel=1e-6)


# ---------------------------------------------------------------------------
# Matching event with NO following event → chf_change_after = None
# ---------------------------------------------------------------------------

def test_matching_event_no_following_event():
    events = [
        "2026-09-01T10:00:00+00:00: new violation — RULE_002",
    ]
    with tempfile.TemporaryDirectory() as tmpdir:
        state_dir = Path(tmpdir)
        _write_state(state_dir, "client2", {}, events)

        result = check_pattern_history("client2", "violation_new", state_dir)

    assert result["occurred_before"] is True
    assert result["occurrences"] == 1
    assert result["sample"][0]["chf_change_after"] is None


def test_matching_event_followed_by_non_value_event():
    events = [
        "2026-09-01T10:00:00+00:00: new violation — RULE_003",
        "2026-09-02T10:00:00+00:00: first briefing generated for this client",
    ]
    with tempfile.TemporaryDirectory() as tmpdir:
        state_dir = Path(tmpdir)
        _write_state(state_dir, "client3", {}, events)

        result = check_pattern_history("client3", "violation_new", state_dir)

    assert result["occurred_before"] is True
    assert result["sample"][0]["chf_change_after"] is None


# ---------------------------------------------------------------------------
# Unknown signal_type → ValueError
# ---------------------------------------------------------------------------

def test_unknown_signal_type_raises_value_error():
    with tempfile.TemporaryDirectory() as tmpdir:
        with pytest.raises(ValueError, match="Unknown signal_type"):
            check_pattern_history("any_client", "not_a_real_signal", Path(tmpdir))


# ---------------------------------------------------------------------------
# position_entered_top signal type
# ---------------------------------------------------------------------------

def test_position_entered_top_signal():
    events = [
        "2026-09-01T10:00:00+00:00: Nestle SA entered top positions (12.5%)",
        "2026-09-02T10:00:00+00:00: portfolio value up 3.2%",
    ]
    with tempfile.TemporaryDirectory() as tmpdir:
        state_dir = Path(tmpdir)
        _write_state(state_dir, "client4", {}, events)

        result = check_pattern_history("client4", "position_entered_top", state_dir)

    assert result["occurred_before"] is True
    assert result["occurrences"] == 1
    assert result["sample"][0]["chf_change_after"] == pytest.approx(0.032, rel=1e-6)


# ---------------------------------------------------------------------------
# position_exited_top signal type
# ---------------------------------------------------------------------------

def test_position_exited_top_signal():
    events = [
        "2026-09-01T10:00:00+00:00: Roche Holding AG dropped out of top positions",
    ]
    with tempfile.TemporaryDirectory() as tmpdir:
        state_dir = Path(tmpdir)
        _write_state(state_dir, "client5", {}, events)

        result = check_pattern_history("client5", "position_exited_top", state_dir)

    assert result["occurred_before"] is True
    assert result["occurrences"] == 1
    assert result["sample"][0]["chf_change_after"] is None


# ---------------------------------------------------------------------------
# Multiple occurrences: sample capped at 3
# ---------------------------------------------------------------------------

def test_sample_capped_at_three():
    events = [
        "2026-09-01T10:00:00+00:00: new violation — RULE_A",
        "2026-09-02T10:00:00+00:00: new violation — RULE_B",
        "2026-09-03T10:00:00+00:00: new violation — RULE_C",
        "2026-09-04T10:00:00+00:00: new violation — RULE_D",
    ]
    with tempfile.TemporaryDirectory() as tmpdir:
        state_dir = Path(tmpdir)
        _write_state(state_dir, "client6", {}, events)

        result = check_pattern_history("client6", "violation_new", state_dir)

    assert result["occurrences"] == 4
    assert len(result["sample"]) == 3


# ---------------------------------------------------------------------------
# All SIGNAL_TYPES are recognised (no ValueError)
# ---------------------------------------------------------------------------

def test_all_signal_types_accepted():
    with tempfile.TemporaryDirectory() as tmpdir:
        for signal_type in SIGNAL_TYPES:
            result = check_pattern_history(
                "no_such_client",
                signal_type,
                Path(tmpdir),
            )
            assert result["occurred_before"] is False
