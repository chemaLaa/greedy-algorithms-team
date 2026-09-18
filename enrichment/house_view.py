"""
Mock bank "House View" / CIO tactical outlook.

MOCK DATA — not a real market forecast, not sourced from any actual bank
publication. The case brief explicitly allows this: "Publicly available
investment reports, market outlooks or CIO publications from established
financial institutions may be used as mock inputs." In production this
would be replaced by an actual feed from the bank's CIO office.

Category names match the real dataset's SAA_* vocabulary exactly
(verified against reference.json's Securities[].SAA_* fields and
StrategicAssetAllocations[].Mappings[].Category — see DATA.md), so
compare_portfolio_to_house_view() can match directly against
data_layer's saa_deviations output with no separate translation step.
"""
from __future__ import annotations

from typing import Optional

HOUSE_VIEW_AS_OF = "2026-09-01"

# stance: "overweight" | "underweight" | "neutral"
# Each item is the bank's current tactical tilt vs. its own strategic
# (long-term) baseline for that category. Not every real category has an
# entry here — a category with no published view means "no active
# tactical call", which is realistic (a bank doesn't hold a strong
# opinion on every single bucket at once).
HOUSE_VIEW = [
    {
        "dimension": "AssetClass",
        "category": "Shares",
        "stance": "overweight",
        "rationale": "Equity earnings momentum remains resilient and valuations are supported by easing rate expectations.",
    },
    {
        "dimension": "AssetClass",
        "category": "Bonds",
        "stance": "underweight",
        "rationale": "Duration risk stays elevated with rate-cut timing uncertain; preference for shorter maturities.",
    },
    {
        "dimension": "AssetClass",
        "category": "Real estate",
        "stance": "neutral",
        "rationale": "Financing costs have stabilized but the sector lacks a clear near-term catalyst.",
    },
    {
        "dimension": "Industry",
        "category": "Information Technology",
        "stance": "overweight",
        "rationale": "AI-driven capex cycle continues to support sector earnings.",
    },
    {
        "dimension": "Industry",
        "category": "Health Care",
        "stance": "overweight",
        "rationale": "Defensive earnings profile attractive given late-cycle uncertainty.",
    },
    {
        "dimension": "Industry",
        "category": "Industrials",
        "stance": "underweight",
        "rationale": "Manufacturing PMIs remain soft across key export markets.",
    },
    {
        "dimension": "Industry",
        "category": "Energy",
        "stance": "underweight",
        "rationale": "Demand growth is moderating while supply stays ample.",
    },
    {
        "dimension": "CurrencyGroup",
        "category": "Swiss francs",
        "stance": "overweight",
        "rationale": "Home-currency preference maintained amid continued franc strength.",
    },
    {
        "dimension": "CurrencyGroup",
        "category": "US-Dollar",
        "stance": "underweight",
        "rationale": "Rate-differential narrowing is expected to weigh on the dollar over coming quarters.",
    },
    {
        "dimension": "CountryGroup",
        "category": "North America",
        "stance": "overweight",
        "rationale": "Continued earnings leadership from large-cap US equities.",
    },
    {
        "dimension": "CountryGroup",
        "category": "Switzerland",
        "stance": "neutral",
        "rationale": "Quality bias intact, but valuations leave limited room for re-rating.",
    },
]


def get_house_view() -> list[dict]:
    """
    Returns the mock house view items. In production, this would pull
    from the bank's actual CIO/house-view publication feed instead of a
    hardcoded list.
    """
    return HOUSE_VIEW


def compare_portfolio_to_house_view(
    portfolio: dict, house_view: Optional[list[dict]] = None
) -> list[dict]:
    """
    For each house view item that has a matching SAA deviation category
    in this portfolio (portfolio["saa_deviations"], from data_layer),
    returns how the client's actual position relates to the bank's
    tactical call:

      "aligned"        — the client's actual weight already tilts the
                          same direction as the house view relative to
                          their own SAA target (e.g. bank overweight
                          Shares, client already above their own Shares
                          target)
      "underexposed"   — bank recommends overweight, client is at/below
                          their own target — an opportunity to lean into
                          the house view
      "overexposed"    — bank recommends underweight, client is at/above
                          their own target — a risk relative to the
                          house view
      "not_applicable" — house view stance is neutral for this category,
                          or the portfolio has no SAA target/actual data
                          for it at all (category skipped in that case)

    Categories with no SAA_deviation row in this portfolio are silently
    skipped — the house view can reference a category this particular
    portfolio has zero SAA target for, and it shouldn't fabricate a
    comparison out of nothing.
    """
    house_view = house_view if house_view is not None else HOUSE_VIEW
    deviations_by_dimension = portfolio.get("saa_deviations") or {}

    result = []
    for item in house_view:
        rows = deviations_by_dimension.get(item["dimension"]) or []
        row = next((r for r in rows if r["category"] == item["category"]), None)
        if row is None:
            continue

        deviation = row.get("deviation_from_target")
        stance = item["stance"]

        if stance == "neutral" or deviation is None:
            relative_position = "not_applicable"
        elif stance == "overweight":
            # Exactly on target (deviation == 0) counts as aligned, not
            # underexposed — the client is already at least at the
            # baseline the bank's overweight call would push them toward.
            relative_position = "aligned" if deviation >= 0 else "underexposed"
        elif stance == "underweight":
            # Symmetric fix: exactly on target counts as aligned, not
            # overexposed — being at (not above) your own target is
            # compliant with an underweight call, not a breach of it.
            # (This also correctly handles a degenerate 0% actual vs. 0%
            # target row — e.g. a category the portfolio's SAA doesn't
            # meaningfully hold at all — as "aligned" rather than
            # fabricating an "overexposed" claim out of two zeros.)
            relative_position = "aligned" if deviation <= 0 else "overexposed"
        else:
            relative_position = "not_applicable"

        result.append(
            {
                "dimension": item["dimension"],
                "category": item["category"],
                "house_view_stance": stance,
                "rationale": item["rationale"],
                "client_actual": row.get("actual"),
                "client_target": row.get("target"),
                "client_deviation_from_target": deviation,
                "relative_position": relative_position,
            }
        )
    return result