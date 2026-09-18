"""
Compares a portfolio's actual exposure against its Strategic Asset
Allocation (SAA) targets, dimension by dimension.

Two conventions from DATA.md drive everything here:
  - Compare using the SAA_* classification fields on Securities
    (SAA_AssetClassName, SAA_CurrencyGroupName, SAA_CountryGroupName,
    SAA_IndustryName), never the plain classification fields — the plain
    fields use a finer taxonomy that won't match SAA target category
    names.
  - Fund positions should contribute their look-through breakdown when
    IsUnbundlingEnabled is true, not just their own top-level
    classification.
"""
from __future__ import annotations

from collections import defaultdict

from .fund_lookthrough import fund_breakdown, is_look_through_eligible
from .reference_index import ReferenceIndex

DIMENSION_TO_SAA_FIELD = {
    "AssetClass": "SAA_AssetClassName",
    "CurrencyGroup": "SAA_CurrencyGroupName",
    "CountryGroup": "SAA_CountryGroupName",
    "Industry": "SAA_IndustryName",
}


def actual_exposure(portfolio: dict, dimension: str, ref: ReferenceIndex) -> dict[str, float]:
    """
    Returns {category_name: weight_fraction} for a portfolio's actual
    security holdings on one SAA dimension, look-through-resolved for
    funds. Cash/account positions carry no SAA_* classification and are
    intentionally excluded — handle cash exposure separately if needed.
    """
    field = DIMENSION_TO_SAA_FIELD.get(dimension)
    if field is None:
        raise ValueError(f"Unknown dimension: {dimension!r}")

    exposure: dict[str, float] = defaultdict(float)

    for pos in portfolio.get("SecurityPositions") or []:
        security_id = pos.get("SecurityId")
        weight = pos.get("PortfolioValuePercentage")  # fraction, 0-1
        if security_id is None or weight is None:
            continue

        if is_look_through_eligible(security_id, ref):
            breakdown = fund_breakdown(security_id, dimension, ref)
            if breakdown:
                for category, fund_weight in breakdown:
                    exposure[category] += weight * fund_weight
                continue
            # Unbundling enabled but no rows for this dimension: fall
            # through and classify the fund itself, below.

        security = ref.security(security_id)
        category = security.get(field) if security else None
        if category is not None:
            exposure[category] += weight

    return dict(exposure)


def saa_targets(portfolio: dict, dimension: str, ref: ReferenceIndex) -> dict[str, dict]:
    """
    Returns {category_name: {"min", "target", "max"}} for one portfolio's
    SAA, one dimension. All fractions (0-1), matching
    Mappings[].MinPercentage/TargetPercentage/MaxPercentage directly.
    """
    saa = ref.saa(portfolio.get("StrategicAssetAllocationId"))
    if not saa:
        return {}

    targets: dict[str, dict] = {}
    for mapping in saa.get("Mappings") or []:
        if mapping.get("Dimension") != dimension:
            continue
        category = mapping.get("Category")
        if category is None:
            continue
        targets[category] = {
            "min": mapping.get("MinPercentage"),
            "target": mapping.get("TargetPercentage"),
            "max": mapping.get("MaxPercentage"),
        }
    return targets


def saa_deviations(portfolio: dict, dimension: str, ref: ReferenceIndex) -> list[dict]:
    """
    One row per category with either an actual holding or an SAA target
    (so both "overweight vs. target" and "target with zero holding" show
    up), each with:

        category, actual, min, target, max,
        deviation_from_target, breaches_min, breaches_max

    `deviation_from_target` is actual - target (positive = overweight).
    `breaches_min`/`breaches_max` are False whenever no min/max is
    defined for that category (nothing to breach).
    """
    actual = actual_exposure(portfolio, dimension, ref)
    targets = saa_targets(portfolio, dimension, ref)

    rows = []
    for category in sorted(set(actual) | set(targets)):
        a = actual.get(category, 0.0)
        t = targets.get(category, {})
        target_pct = t.get("target")
        min_pct = t.get("min")
        max_pct = t.get("max")
        rows.append(
            {
                "category": category,
                "actual": a,
                "min": min_pct,
                "target": target_pct,
                "max": max_pct,
                "deviation_from_target": (a - target_pct) if target_pct is not None else None,
                "breaches_min": min_pct is not None and a < min_pct,
                "breaches_max": max_pct is not None and a > max_pct,
            }
        )
    return rows
