"""
Bank "House View" / CIO tactical outlook, and how a client's portfolio
relates to it.

MOCK DATA — not a real market forecast, not sourced from any actual bank
publication. The case brief explicitly allows this: "Publicly available
investment reports, market outlooks or CIO publications from established
financial institutions may be used as mock inputs." In production this
would be replaced by an actual feed from the bank's CIO office — see
HouseViewProvider below for the seam that swap happens through.

Category names match the real dataset's SAA_* vocabulary exactly
(verified against reference.json's Securities[].SAA_* fields and
StrategicAssetAllocations[].Mappings[].Category — see DATA.md), so
compare_portfolio_to_house_view() can match directly against
data_layer's saa_deviations output with no separate translation step.
"""
from __future__ import annotations

from typing import Optional, Protocol

HOUSE_VIEW_AS_OF = "2026-09-01"

# A tactical house view is external market commentary, never a rule. It
# never overrides what the client's own suitability profile, compliance
# violations, or SAA targets require — this sentence is deliberately a
# module-level constant (not just a code comment) so prompt_builder.py can
# import and surface it verbatim in the LLM-facing text, rather than that
# precedence rule living only as an internal assumption nothing downstream
# ever actually states.
HOUSE_VIEW_PRECEDENCE_NOTE = (
    "This house view is external tactical market commentary. It never "
    "overrides the client's suitability profile, active compliance "
    "violations, or the portfolio's own SAA targets — treat it as "
    "context for the conversation, not as a directive."
)

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


class HouseViewProvider(Protocol):
    def get_house_view(self) -> list[dict]:
        """
        Returns tactical house-view rows: {dimension, category, stance,
        rationale, as_of, source, is_mock}. Every row MUST carry as_of
        (str date the view was published), source (str, e.g. "mock" or a
        real CIO feed name), and is_mock (bool) — compare_portfolio_to_
        house_view() and the prompt-facing text depend on these being
        present rather than guessing where a call came from.
        """
        ...


class MockHouseViewProvider:
    """
    Wraps this module's hardcoded mock house view (see module docstring)
    and tags every row is_mock=True, source="mock". This is the default
    provider used everywhere unless a real feed is wired in.
    """

    def __init__(self, house_view: Optional[list[dict]] = None, as_of: str = HOUSE_VIEW_AS_OF):
        self._house_view = house_view if house_view is not None else HOUSE_VIEW
        self._as_of = as_of

    def get_house_view(self) -> list[dict]:
        return [
            {**item, "as_of": self._as_of, "source": "mock", "is_mock": True}
            for item in self._house_view
        ]


class StaticHouseViewProvider:
    """
    Wraps a fixed, already-fetched set of house-view items from a named,
    non-mock source (e.g. a CIO publication snapshot saved to a file) —
    for when a real house view exists but isn't a live feed. Rows default
    to is_mock=False, but per-row overrides on the input items win, so a
    caller can mix mock and real rows in one provider if it ever needs to.
    """

    def __init__(self, house_view: list[dict], *, source: str, as_of: str, is_mock: bool = False):
        self._house_view = house_view
        self._source = source
        self._as_of = as_of
        self._is_mock = is_mock

    def get_house_view(self) -> list[dict]:
        return [
            {
                **item,
                "as_of": item.get("as_of", self._as_of),
                "source": item.get("source", self._source),
                "is_mock": item.get("is_mock", self._is_mock),
            }
            for item in self._house_view
        ]


def get_house_view(provider: Optional[HouseViewProvider] = None) -> list[dict]:
    """
    Returns the active house view's rows, already tagged with as_of /
    source / is_mock. Defaults to MockHouseViewProvider() when no
    provider is given, matching this repo's current (mock) state.
    """
    provider = provider if provider is not None else MockHouseViewProvider()
    return provider.get_house_view()


def compare_portfolio_to_house_view(
    portfolio: dict, provider: Optional[HouseViewProvider] = None
) -> list[dict]:
    """
    For each house view item that has a matching SAA deviation category
    in this portfolio (portfolio["saa_deviations"], from data_layer),
    returns how the client's actual position relates to the bank's
    tactical call, as one of four explicit states:

      "aligned"        — the client's actual weight already tilts the
                          same direction as the house view, past their
                          own SAA target (e.g. bank overweight Shares,
                          client's actual weight is above their own
                          Shares target)
      "opposite"       — the client's actual weight tilts away from the
                          direction the house view recommends relative to
                          their own target (whether that's a risk — bank
                          underweight, client above target — or a missed
                          opportunity — bank overweight, client below
                          target: either way, action worth raising)
      "at_target"      — the client is sitting exactly at their own SAA
                          target for this category. This is deliberately
                          NOT "aligned": a house view of "overweight" or
                          "underweight" is a call to tilt AWAY from the
                          strategic baseline, and being exactly at that
                          baseline means the client hasn't acted on the
                          tactical call in either direction — it should
                          never be narrated as if they had.
      "not_applicable" — house view stance is neutral for this category,
                          or the portfolio has no SAA target/actual data
                          for it at all (category skipped in that case)

    Categories with no SAA_deviation row in this portfolio are silently
    skipped — the house view can reference a category this particular
    portfolio has zero SAA target for, and it shouldn't fabricate a
    comparison out of nothing.
    """
    house_view = get_house_view(provider)
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
        elif deviation == 0:
            relative_position = "at_target"
        elif stance == "overweight":
            relative_position = "aligned" if deviation > 0 else "opposite"
        elif stance == "underweight":
            relative_position = "aligned" if deviation < 0 else "opposite"
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
                "as_of": item.get("as_of"),
                "source": item.get("source"),
                "is_mock": item.get("is_mock"),
            }
        )
    return result
