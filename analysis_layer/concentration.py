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


def concentration_snapshot(
    portfolio: dict,
    ref: "ReferenceIndex | None" = None,
    *,
    n_positions: int = 5,
    n_categories: int = 3,
    dimensions: tuple[str, ...] = ("AssetClass", "CurrencyGroup", "CountryGroup", "Industry"),
) -> dict:
    result = {"largest_positions": largest_single_positions(portfolio, n=n_positions), "dimensions": {}}
    if ref is not None:
        for dimension in dimensions:
            result["dimensions"][dimension] = dimension_concentration(portfolio, dimension, ref, n=n_categories)
    return result
