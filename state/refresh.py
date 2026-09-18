"""
Ties snapshot + diff + store + events together — the one function the
API layer calls after computing a client's priorities. This is what
replaces "re-derive everything from the full history every time" with
"what changed since we last looked".
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .diff import diff_portfolio_snapshots
from .events import summarize_diff_as_events
from .snapshot import build_portfolio_snapshot
from .store import DEFAULT_STATE_DIR, load_client_state, save_client_state

MAX_EVENTS = 20


def refresh_client_state(
    client_view: dict, priority_bundles: list[dict], state_dir: Path = DEFAULT_STATE_DIR
) -> dict[str, Any]:
    """
    client_view: data_layer.build_client_view() output
    priority_bundles: analysis_layer.build_client_priorities() output for
        the SAME client_view, same order as client_view["portfolios"]
        (build_client_priorities already produces them in that order, so
        the common call is just:
            refresh_client_state(view, build_client_priorities(view, ref))
        )

    Returns:
        {
          "portfolios": {portfolio_id: {"snapshot": ..., "diff": ...}, ...},
          "events_log": [str, ...],
        }

    As a side effect, persists the new snapshots as the baseline for next
    time — so calling this twice in a row for the same client (nothing
    having actually changed in between) correctly shows an EMPTY diff on
    the second call, not because the data didn't move, but because
    nothing moved SINCE the first call.
    """
    client_ref = client_view["client_ref"]
    stored = load_client_state(client_ref, state_dir)
    previous_snapshots: dict = stored.get("snapshots", {})
    events_log: list[str] = list(stored.get("events", []))

    new_snapshots: dict[str, dict] = {}
    portfolios_result: dict[str, dict] = {}

    for portfolio, bundle in zip(client_view["portfolios"], priority_bundles):
        portfolio_id = str(portfolio.get("PortfolioId"))
        snapshot = build_portfolio_snapshot(portfolio, bundle)
        previous = previous_snapshots.get(portfolio_id)
        diff = diff_portfolio_snapshots(previous, snapshot)

        events_log.extend(summarize_diff_as_events(diff, snapshot["captured_at"]))

        new_snapshots[portfolio_id] = snapshot
        portfolios_result[portfolio_id] = {"snapshot": snapshot, "diff": diff}

    events_log = events_log[-MAX_EVENTS:]

    save_client_state(
        client_ref, {"snapshots": new_snapshots, "events": events_log}, state_dir
    )

    return {"portfolios": portfolios_result, "events_log": events_log}
