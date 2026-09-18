import tempfile
from pathlib import Path

from state.store import load_client_state, save_client_state
from state.refresh import refresh_client_state
from helpers import first_client
from data_layer import build_client_view
from analysis_layer import build_client_priorities


def _tmp_dir():
    return Path(tempfile.mkdtemp())


def test_load_client_state_returns_empty_shape_when_no_file():
    state = load_client_state("NEVER-SEEN-CLIENT", state_dir=_tmp_dir())
    assert state == {"snapshots": {}, "events": []}


def test_save_then_load_round_trips():
    state_dir = _tmp_dir()
    payload = {"snapshots": {"1": {"portfolio_value": 100}}, "events": ["hello"]}
    save_client_state("CASE-001", payload, state_dir=state_dir)
    loaded = load_client_state("CASE-001", state_dir=state_dir)
    assert loaded == payload


def test_refresh_first_call_marks_first_interaction():
    client, ref = first_client()
    view = build_client_view(client, ref)
    bundles = build_client_priorities(view, ref)
    state_dir = _tmp_dir()

    result = refresh_client_state(view, bundles, state_dir=state_dir)
    portfolio_id = str(view["portfolios"][0]["PortfolioId"])
    assert result["portfolios"][portfolio_id]["diff"]["is_first_interaction"] is True


def test_refresh_second_call_with_no_changes_is_empty_diff():
    client, ref = first_client()
    view = build_client_view(client, ref)
    bundles = build_client_priorities(view, ref)
    state_dir = _tmp_dir()

    refresh_client_state(view, bundles, state_dir=state_dir)
    result = refresh_client_state(view, bundles, state_dir=state_dir)

    portfolio_id = str(view["portfolios"][0]["PortfolioId"])
    diff = result["portfolios"][portfolio_id]["diff"]
    assert diff["is_first_interaction"] is False
    assert diff["violations_new"] == []
    assert diff["violations_resolved"] == []


def test_refresh_persists_state_for_next_call():
    client, ref = first_client()
    view = build_client_view(client, ref)
    bundles = build_client_priorities(view, ref)
    state_dir = _tmp_dir()

    refresh_client_state(view, bundles, state_dir=state_dir)
    stored = load_client_state(view["client_ref"], state_dir=state_dir)
    portfolio_id = str(view["portfolios"][0]["PortfolioId"])
    assert portfolio_id in stored["snapshots"]
    assert len(stored["events"]) >= 1


def test_events_log_capped_at_max_events():
    from state.refresh import MAX_EVENTS

    client, ref = first_client()
    view = build_client_view(client, ref)
    bundles = build_client_priorities(view, ref)
    state_dir = _tmp_dir()

    # Pre-seed with more events than the cap to check trimming, not to
    # simulate a realistic history.
    save_client_state(
        view["client_ref"],
        {"snapshots": {}, "events": [f"fake event {i}" for i in range(MAX_EVENTS + 10)]},
        state_dir=state_dir,
    )
    result = refresh_client_state(view, bundles, state_dir=state_dir)
    assert len(result["events_log"]) <= MAX_EVENTS
