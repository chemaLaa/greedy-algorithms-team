"""
Concentration checks — how much of the portfolio sits in one place, at
two levels: individual security lines, and rolled-up exposure per
dimension (asset class / currency / country / industry), the latter
reusing data_layer.saa's fund-look-through-aware aggregation so a fund's
underlying holdings count correctly rather than as one opaque line.
"""
from __future__ import annotations

from data_layer.reference_index import ReferenceIndex
from data_layer.saa import actual_exposure


def largest_single_positions(portfolio: dict, n: int = 5) -> list[dict]:
    """
    Top N security positions by PortfolioValuePercentage, largest first.
    Deliberately at the position-line level (fund positions included as
    themselves, not unpacked) — this is "how big is any one line in the
    portfolio", not look-through exposure. Use dimension_concentration()
    for the look-through view.
    """
    positions = portfolio.get("SecurityPositions") or []
    ranked = sorted(
        positions, key=lambda p: p.get("PortfolioValuePercentage") or 0.0, reverse=True
    )
    return [
        {
            "SecurityId": p.get("SecurityId"),
            "SecurityName": p.get("SecurityName"),
            "PortfolioValuePercentage": p.get("PortfolioValuePercentage"),
        }
        for p in ranked[:n]
    ]


def dimension_concentration(
    portfolio: dict, dimension: str, ref: ReferenceIndex, n: int = 3
) -> list[dict]:
    """
    Top N categories by actual exposure on one SAA dimension
    ("AssetClass" | "CurrencyGroup" | "CountryGroup" | "Industry"),
    fund-look-through-aware. Thin wrapper over data_layer.saa.actual_exposure
    — kept here rather than duplicated, since "what's the biggest
    concentration" and "how does this compare to target" are two different
    questions over the same underlying exposure numbers.
    """
    exposure = actual_exposure(portfolio, dimension, ref)
    ranked = sorted(exposure.items(), key=lambda kv: kv[1], reverse=True)
    return [{"category": category, "weight": weight} for category, weight in ranked[:n]]
