"""Deterministic concentration analysis.

Single-position concentration is line-level. Dimension concentration uses the
fund-look-through-aware exposure logic from ``data_layer.saa`` when available.
"""
from __future__ import annotations

import math
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from data_layer.reference_index import ReferenceIndex


def _finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def largest_single_positions(portfolio: dict, n: int = 5) -> list[dict]:
    """Top N security lines by absolute portfolio weight.

    Absolute magnitude is used so a large short position is not silently
    ignored. The signed weight is preserved in the output.
    """
    positions = []
    for p in portfolio.get("SecurityPositions") or []:
        if isinstance(p, dict) and _finite(p.get("PortfolioValuePercentage")):
            positions.append(p)
    ranked = sorted(positions, key=lambda p: abs(float(p["PortfolioValuePercentage"])), reverse=True)
    return [
        {
            "SecurityId": p.get("SecurityId"),
            "SecurityName": p.get("SecurityName"),
            "PortfolioValuePercentage": float(p["PortfolioValuePercentage"]),
            "absolute_weight": abs(float(p["PortfolioValuePercentage"])),
        }
        for p in ranked[:n]
    ]


def dimension_concentration(portfolio: dict, dimension: str, ref: "ReferenceIndex", n: int = 3) -> list[dict]:
    """Top N fund-look-through-aware categories for one SAA dimension."""
    # Lazy import keeps validation/audit usable before the full data layer is imported.
    from data_layer.saa import actual_exposure

    exposure = actual_exposure(portfolio, dimension, ref)
    ranked = sorted(exposure.items(), key=lambda kv: abs(kv[1]), reverse=True)
    return [
        {"category": category, "weight": weight, "absolute_weight": abs(weight)}
        for category, weight in ranked[:n]
    ]


def non_base_currency_exposure(portfolio: dict) -> Optional[float]:
    """
    Fraction of the portfolio (by absolute weight) held in a position whose
    own `Currency` differs from the portfolio's own `PortfolioCurrency`.

    This is a genuine, code-computed currency-EXPOSURE fact — NOT an FX
    return-attribution number. The schema has no historical FX-rate table,
    so the actual contribution of currency movements to a given value
    change can't be computed from this data, and must never be estimated
    by the LLM either; this figure only tells you how much of the
    portfolio COULD plausibly be affected by FX moves, not by how much it
    actually was.

    Returns None if `PortfolioCurrency` itself is missing — there's no
    base to compare position currencies against, so classifying any
    position as "non-base" would be a guess, not a fact.
    """
    base_currency = portfolio.get("PortfolioCurrency")
    if not base_currency:
        return None

    exposure = 0.0
    for pos in (portfolio.get("SecurityPositions") or []) + (portfolio.get("AccountPositions") or []):
        if not isinstance(pos, dict):
            continue
        weight = pos.get("PortfolioValuePercentage")
        currency = pos.get("Currency")
        if not _finite(weight) or not currency:
            continue
        if currency != base_currency:
            exposure += abs(float(weight))
    return exposure


def concentration_snapshot(
    portfolio: dict,
    ref: "ReferenceIndex | None" = None,
    *,
    n_positions: int = 5,
    n_categories: int = 3,
    dimensions: tuple[str, ...] = ("AssetClass", "CurrencyGroup", "CountryGroup", "Industry"),
) -> dict:
    result = {
        "largest_positions": largest_single_positions(portfolio, n=n_positions),
        "dimensions": {},
        "non_base_currency_exposure": non_base_currency_exposure(portfolio),
    }
    if ref is not None:
        for dimension in dimensions:
            result["dimensions"][dimension] = dimension_concentration(portfolio, dimension, ref, n=n_categories)
    return result
