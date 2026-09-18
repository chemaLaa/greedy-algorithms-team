"""
Assembles everything data_layer / analysis_layer / state / enrichment
produced into one structured BriefingContext. Plain data, no prose, no
LLM call — this is the single object prompt_builder.py turns into an
actual prompt.

Deliberately takes already-computed pieces as arguments rather than
recomputing anything itself — this module's only job is shaping and
labeling, so it stays trivially testable without needing a
ReferenceIndex, a client file, or a network call.
"""
from __future__ import annotations

from typing import Optional


def build_briefing_context(
    client_view: dict,
    priority_bundle: dict,
    state_result: Optional[dict] = None,
    house_view_alignment: Optional[list[dict]] = None,
    news_articles: Optional[list[dict]] = None,
) -> dict:
    """
    client_view: data_layer.build_client_view() output
    priority_bundle: ONE portfolio's bundle from
        analysis_layer.build_client_priorities() — i.e. one element of
        that list, not the whole list (a BriefingContext is per-portfolio,
        matching how a briefing is generated: one client call, one
        portfolio in view)
    state_result: state.refresh_client_state()["portfolios"][portfolio_id],
        i.e. ONE portfolio's {"snapshot", "diff"} entry — or None if the
        state layer wasn't used for this call (falls back to the
        analysis_layer note-date proxy, see change_since_last_interaction
        below)
    house_view_alignment: enrichment.house_view.compare_portfolio_to_house_view()
        output for this portfolio
    news_articles: enrichment.market_news.fetch_relevant_news() output
        for this portfolio

    Returns a BriefingContext dict (see README for the full shape).
    """
    portfolio_id = priority_bundle["portfolio_id"]
    portfolio = next(
        (p for p in client_view["portfolios"] if p.get("PortfolioId") == portfolio_id),
        None,
    )

    return {
        "client": _client_section(client_view),
        "portfolio": _portfolio_section(client_view, portfolio, priority_bundle),
        "priorities": priority_bundle.get("priorities", []),
        "top_risk_contributors": priority_bundle.get("top_risk_contributors", []),
        "change_since_last_interaction": _change_section(priority_bundle, state_result),
        "house_view_alignment": house_view_alignment or [],
        "market_news": news_articles or [],
    }


def _client_section(client_view: dict) -> dict:
    risk_profile = client_view.get("risk_profile")
    esg_profile = client_view.get("esg_profile")
    return {
        "name": client_view.get("display_name"),
        "risk_profile": risk_profile.get("Name") if risk_profile else None,
        "esg_profile": esg_profile.get("Name") if esg_profile else None,
    }


def _portfolio_section(client_view: dict, portfolio: Optional[dict], priority_bundle: dict) -> dict:
    return {
        "portfolio_id": priority_bundle.get("portfolio_id"),
        "portfolio_name": priority_bundle.get("portfolio_name"),
        "value": portfolio.get("AssetsUnderManagementInDefaultCurrency") if portfolio else None,
        "reporting_currency": client_view.get("reporting_currency"),
        "performance_trend": priority_bundle.get("performance"),
    }


def _change_section(priority_bundle: dict, state_result: Optional[dict]) -> dict:
    """
    Prefers the exact state-layer diff when available (see
    state/refresh.py) over analysis_layer's note-date proxy, which is
    known to be imprecise ~40% of the time — see
    analysis_layer/material_changes.py and the README for why. The
    "source" field lets prompt_builder.py phrase this with appropriate
    confidence either way, rather than presenting a guess as a fact.
    """
    if state_result is not None:
        diff = state_result.get("diff", {})
        return {
            "source": "state_diff",
            "is_first_interaction": diff.get("is_first_interaction"),
            "details": diff,
        }

    return {
        "source": "note_date_proxy",
        "is_first_interaction": None,
        "details": priority_bundle.get("change_since_last_interaction"),
    }
