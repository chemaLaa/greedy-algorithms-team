"""
Deterministic portfolio-performance analysis — no LLM calls here. This
answers "what actually happened, in numbers" using only what data_layer
already resolved, so the synthesis layer gets firm facts to narrate
instead of guessing at them.

Scope note: the schema gives per-position RISK contribution
(ContributionVolatility) but no per-position RETURN contribution — only
portfolio-level PerformanceYTD / PerformanceHistory exist for that. So
"largest contributor" below means largest contributor to portfolio risk,
not return — there's no data to compute a per-position return
contribution, and pretending otherwise would be fabricating a number.
"""
from __future__ import annotations

from typing import Optional


def performance_trend(portfolio: dict) -> dict:
    """
    Summarizes the portfolio's value trend from PerformanceHistory
    (monthly NAV points, ~5 years per DATA.md). Returns None fields when
    there's insufficient history (0 or 1 points) rather than raising.
    """
    history = portfolio.get("PerformanceHistory") or []
    if len(history) < 2:
        return {
            "latest_value": history[0]["Value"] if history else None,
            "latest_date": history[0]["Date"] if history else None,
            "previous_value": None,
            "previous_date": None,
            "change_since_previous_point": None,
            "change_since_previous_point_pct": None,
            "performance_ytd": portfolio.get("PerformanceYTD"),
            "months_of_history": len(history),
        }

    latest, previous = history[-1], history[-2]
    change = latest["Value"] - previous["Value"]
    change_pct = (change / previous["Value"]) if previous["Value"] else None

    return {
        "latest_value": latest["Value"],
        "latest_date": latest["Date"],
        "previous_value": previous["Value"],
        "previous_date": previous["Date"],
        "change_since_previous_point": change,
        "change_since_previous_point_pct": change_pct,
        "performance_ytd": portfolio.get("PerformanceYTD"),
        "months_of_history": len(history),
    }


def top_risk_contributors(portfolio: dict, n: int = 5) -> list[dict]:
    """
    Ranks security positions by ContributionVolatility — the figure that
    actually sums to Portfolio.Volatility across all positions (see
    DATA.md; MarginalContributionToRisk does NOT sum to it, so it's
    deliberately not used here) — largest first.

    Returns [{SecurityId, SecurityName, PortfolioValuePercentage,
    ContributionVolatility, share_of_portfolio_volatility}], where
    share_of_portfolio_volatility is this position's ContributionVolatility
    divided by the portfolio's total Volatility (None if that total is
    missing or zero, rather than raising a ZeroDivisionError).
    """
    positions = portfolio.get("SecurityPositions") or []
    total_vol: Optional[float] = portfolio.get("Volatility")

    ranked = sorted(
        positions,
        key=lambda p: p.get("ContributionVolatility") or 0.0,
        reverse=True,
    )

    result = []
    for pos in ranked[:n]:
        cv = pos.get("ContributionVolatility")
        share = (cv / total_vol) if (cv is not None and total_vol) else None
        result.append(
            {
                "SecurityId": pos.get("SecurityId"),
                "SecurityName": pos.get("SecurityName"),
                "PortfolioValuePercentage": pos.get("PortfolioValuePercentage"),
                "ContributionVolatility": cv,
                "share_of_portfolio_volatility": share,
            }
        )
    return result
