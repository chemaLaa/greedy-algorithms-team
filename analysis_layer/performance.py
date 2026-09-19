"""Deterministic portfolio value/risk analysis.

Numerical facts are computed here; the LLM must not perform arithmetic.
``PerformanceHistory[].Value`` is treated as a portfolio-value observation,
not as an investment return, unless UnRiskOmega explicitly confirms otherwise.
"""
from __future__ import annotations

from datetime import date, datetime
import math
from typing import Any, Optional

from .validation import (
    validate_current_portfolio_metrics,
    validate_performance_history,
    validate_risk_contributions,
)


def _finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _parse_date(value: str) -> date:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).date()


def _usable_history(portfolio: dict) -> list[dict]:
    rows = []
    for row in portfolio.get("PerformanceHistory") or []:
        if not isinstance(row, dict) or not isinstance(row.get("Date"), str) or not _finite(row.get("Value")):
            continue
        try:
            d = _parse_date(row["Date"])
        except ValueError:
            continue
        rows.append({"date": d, "date_raw": row["Date"], "value": float(row["Value"])})
    rows.sort(key=lambda x: x["date"])
    return rows


def _subtract_months(d: date, months: int) -> date:
    total = d.year * 12 + (d.month - 1) - months
    year, month0 = divmod(total, 12)
    month = month0 + 1
    # Day 1 is sufficient because partner history is observation-based and we
    # select the latest observation on/before the target month boundary.
    return date(year, month, 1)


def _change(base: dict, latest: dict) -> dict:
    absolute = latest["value"] - base["value"]
    pct = absolute / base["value"] if base["value"] else None
    return {
        "base_date": base["date"].isoformat(),
        "base_value": base["value"],
        "latest_date": latest["date"].isoformat(),
        "latest_value": latest["value"],
        "change": absolute,
        "change_pct": pct,
    }


def _point_on_or_before(rows: list[dict], target: date) -> Optional[dict]:
    candidates = [r for r in rows if r["date"] <= target]
    return candidates[-1] if candidates else None


def performance_trend(portfolio: dict) -> dict:
    """Compact, quality-aware summary of the portfolio-value history.

    Backward-compatible keys for the previous-point change are preserved, but
    new callers should prefer the explicit ``value_changes`` object.
    """
    quality = validate_performance_history(portfolio)
    rows = _usable_history(portfolio)

    provided_ytd = portfolio.get("PerformanceYTD")
    if not _finite(provided_ytd):
        provided_ytd = None

    if not rows:
        return {
            "status": quality["status"],
            "reasons": quality.get("reasons", []),
            "semantics": "portfolio_value_change_not_confirmed_return",
            "latest_value": None,
            "latest_date": None,
            "previous_value": None,
            "previous_date": None,
            "change_since_previous_point": None,
            "change_since_previous_point_pct": None,
            "performance_ytd": provided_ytd,
            "performance_ytd_source": "provided" if provided_ytd is not None else "unavailable",
            "history_point_count": 0,
            "value_changes": {},
        }

    latest = rows[-1]
    previous = rows[-2] if len(rows) >= 2 else None
    previous_change = _change(previous, latest) if previous else None

    horizon_changes: dict[str, Optional[dict]] = {}
    for months in (3, 12):
        target = _subtract_months(latest["date"], months)
        base = _point_on_or_before(rows, target)
        horizon_changes[f"{months}m"] = _change(base, latest) if base and base != latest else None

    year_start = date(latest["date"].year, 1, 1)
    ytd_base = _point_on_or_before(rows, year_start)
    horizon_changes["since_year_start"] = _change(ytd_base, latest) if ytd_base and ytd_base != latest else None

    return {
        "status": quality["status"],
        "reasons": quality.get("reasons", []),
        "semantics": "portfolio_value_change_not_confirmed_return",
        "return_semantics_confirmed": False,
        "latest_value": latest["value"],
        "latest_date": latest["date"].isoformat(),
        "previous_value": previous["value"] if previous else None,
        "previous_date": previous["date"].isoformat() if previous else None,
        "change_since_previous_point": previous_change["change"] if previous_change else None,
        "change_since_previous_point_pct": previous_change["change_pct"] if previous_change else None,
        "performance_ytd": provided_ytd,
        "performance_ytd_source": "provided" if provided_ytd is not None else "unavailable",
        "history_point_count": len(rows),
        "earliest_date": rows[0]["date"].isoformat(),
        "value_changes": horizon_changes,
    }


def current_risk_return_snapshot(portfolio: dict) -> dict:
    """Current URO-style risk/expected-return metrics, without calling them performance."""
    quality = validate_current_portfolio_metrics(portfolio)
    return {
        "status": quality["status"],
        "reasons": quality.get("reasons", []),
        "volatility": quality.get("volatility"),
        "expected_return": quality.get("expected_return"),
        "value_at_risk": quality.get("value_at_risk"),
        "expected_return_semantics": "forward_looking_expected_return",
    }


def risk_contributor_analysis(portfolio: dict, n: int = 5) -> dict:
    """Quality-gated risk attribution across security *and account* positions.

    Positive contributors and negative risk reducers are returned separately.
    If attribution does not reconcile to portfolio volatility, no ranked claim
    is emitted.
    """
    quality = validate_risk_contributions(portfolio)
    if quality["status"] in {"invalid", "unavailable"}:
        return {
            "status": quality["status"],
            "reasons": quality.get("reasons", []),
            "contributors": [],
            "risk_reducers": [],
            "quality": quality,
        }

    total_vol = portfolio.get("Volatility")
    total_vol = float(total_vol) if _finite(total_vol) and float(total_vol) != 0 else None

    rows: list[dict] = []
    for kind, collection in (("security", "SecurityPositions"), ("account", "AccountPositions")):
        for pos in portfolio.get(collection) or []:
            if not isinstance(pos, dict) or not _finite(pos.get("ContributionVolatility")):
                continue
            cv = float(pos["ContributionVolatility"])
            weight = float(pos["PortfolioValuePercentage"]) if _finite(pos.get("PortfolioValuePercentage")) else None
            share = cv / total_vol if total_vol is not None else None
            intensity = share / abs(weight) if share is not None and weight not in (None, 0.0) else None
            rows.append({
                "position_type": kind,
                "SecurityId": pos.get("SecurityId"),
                "SecurityName": pos.get("SecurityName") if kind == "security" else pos.get("AccountName"),
                "AccountName": pos.get("AccountName") if kind == "account" else None,
                "PortfolioValuePercentage": weight,
                "ContributionVolatility": cv,
                "share_of_portfolio_volatility": share,
                "risk_intensity_vs_weight": intensity,
            })

    contributors = sorted((r for r in rows if r["ContributionVolatility"] > 0), key=lambda r: r["ContributionVolatility"], reverse=True)[:n]
    reducers = sorted((r for r in rows if r["ContributionVolatility"] < 0), key=lambda r: r["ContributionVolatility"])[:n]

    return {
        "status": quality["status"],
        "reasons": quality.get("reasons", []),
        "contributors": contributors,
        "risk_reducers": reducers,
        "quality": quality,
    }


def top_risk_contributors(portfolio: dict, n: int = 5) -> list[dict]:
    """Backward-compatible list API for callers that only need positive contributors."""
    return risk_contributor_analysis(portfolio, n=n)["contributors"]
