"""
Builds a compact, storable "state snapshot" for one portfolio, from
already-computed data_layer + analysis_layer output.

Deliberately NOT the full client_view — that's large and fully
re-derivable from the source files on every run. A snapshot is the small
set of numbers that answering "what changed since we last looked at this
client" actually needs: portfolio value, allocation by dimension, the
current top positions, and the set of active violation codes.
"""
from __future__ import annotations

from datetime import datetime, timezone

TOP_POSITIONS_TRACKED = 5


def build_portfolio_snapshot(portfolio: dict, priorities_bundle: dict) -> dict:
    """
    portfolio: one entry from client_view["portfolios"] (data_layer output)
    priorities_bundle: the matching entry from
        analysis_layer.build_client_priorities() for the SAME portfolio
        (same PortfolioId) — pass them in lockstep, see state.refresh
    """
    allocation = {
        dimension: {row["category"]: row["actual"] for row in rows}
        for dimension, rows in (portfolio.get("saa_deviations") or {}).items()
    }

    positions = portfolio.get("resolved_security_positions") or []
    top_positions = [
        {
            "SecurityId": p.get("SecurityId"),
            "SecurityName": p.get("SecurityName"),
            "weight": p.get("PortfolioValuePercentage"),
        }
        for p in sorted(
            positions, key=lambda p: p.get("PortfolioValuePercentage") or 0.0, reverse=True
        )[:TOP_POSITIONS_TRACKED]
    ]

    violations = sorted(
        {
            item["rule_code"]
            for item in priorities_bundle.get("priorities", [])
            if item["type"] == "violation"
        }
    )

    return {
        "portfolio_id": portfolio.get("PortfolioId"),
        # Real wall-clock time this snapshot was taken — NOT one of the
        # shifted dates inside the source data (see DATA.md), since this
        # timestamp tracks our own observation history, not client events.
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "portfolio_value": portfolio.get("AssetsUnderManagementInDefaultCurrency"),
        "allocation": allocation,
        "top_positions": top_positions,
        "violations": violations,
    }
