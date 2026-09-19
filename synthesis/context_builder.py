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

from enrichment.market_news import clean_security_name

# "A small pool of advisory notes" per DATA.md (today: 5-6 per client) —
# capped anyway rather than assuming that stays true of tomorrow's data,
# matching this codebase's pattern of explicit budgets everywhere else
# (market_news's BUDGET_MAX_* constants, house_view's max_actionable).
CLIENT_NOTES_MAX = 5


def build_briefing_context(
    client_view: dict,
    priority_bundle: dict,
    state_result: Optional[dict] = None,
    house_view_alignment: Optional[list[dict]] = None,
    news_articles: Optional[list[dict]] = None,
    news_bundle: Optional[dict] = None,
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
    news_articles: enrichment.market_news.fetch_relevant_news() output for
        this portfolio (backward-compatible list-only form; prefer
        news_bundle when you have it)
    news_bundle: enrichment.market_news.fetch_relevant_news_bundle() output
        for this portfolio — preferred over news_articles because it
        carries the fetch status (a genuine provider/network failure must
        never be narrated the same way as "no relevant news found"; see
        market_news.py). When both are given, news_bundle wins.

    Returns a BriefingContext dict (see README for the full shape).
    """
    portfolio_id = priority_bundle["portfolio_id"]
    portfolio = next(
        (p for p in client_view["portfolios"] if p.get("PortfolioId") == portfolio_id),
        None,
    )

    if news_bundle is not None:
        market_news = news_bundle.get("articles") or []
        market_news_status = {
            "status": news_bundle.get("status"),
            "reasons": news_bundle.get("reasons", []),
        }
    else:
        market_news = news_articles or []
        # No bundle to consult, so the most that can honestly be said is
        # whether anything came back — never fabricate a fetch_failed vs.
        # no_news_found distinction this caller didn't actually provide.
        market_news_status = {"status": "ok" if market_news else "unavailable", "reasons": []}

    client_notes = _client_notes_section(client_view)
    client_interests = _client_interests_section(client_view)
    house_view_alignment = house_view_alignment or []
    priorities = priority_bundle.get("priorities", [])
    top_risk_contributors = priority_bundle.get("top_risk_contributors", [])

    return {
        "client": _client_section(client_view),
        "client_notes": client_notes,
        "client_interests": client_interests,
        "portfolio": _portfolio_section(client_view, portfolio, priority_bundle),
        "priorities": priorities,
        "top_risk_contributors": top_risk_contributors,
        "change_since_last_interaction": _change_section(priority_bundle, state_result),
        "house_view_alignment": house_view_alignment,
        "market_news": market_news,
        "market_news_status": market_news_status,
        "attribution_caveat": _attribution_caveat_section(priority_bundle),
        "sources": _sources_section(
            priorities=priorities,
            top_risk_contributors=top_risk_contributors,
            house_view_alignment=house_view_alignment,
            market_news=market_news,
            client_notes=client_notes,
            client_interests=client_interests,
        ),
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


def _client_notes_section(client_view: dict, max_notes: int = CLIENT_NOTES_MAX) -> list[dict]:
    """
    CRM-style advisory notes (ClientNotes[].Note) — free text an advisor
    has recorded about this client's circumstances, preferences, and
    exclusions (e.g. "no direct positions in fossil fuels", "prefers a
    cash reserve for medical expenses", "power of attorney for a family
    member's portfolio"). Previously loaded into client_view["notes"] by
    data_layer but only ever consulted for its DATE (as an interaction-date
    proxy elsewhere) — the actual text never reached the model. This is
    the seam that fixes that: real client-specific circumstances, plain
    data, most-recent-first, capped at max_notes.

    A note missing its own text is skipped rather than surfaced as an
    empty bullet the model would have to guess the meaning of.
    """
    notes = client_view.get("notes") or []
    parsed = []
    for note in notes:
        if not isinstance(note, dict):
            continue
        text = note.get("Note")
        if not text:
            continue
        parsed.append({"date": note.get("CreatedByDateUTC"), "text": text})

    parsed.sort(key=lambda n: n["date"] or "", reverse=True)
    return parsed[:max_notes]


def _client_interests_section(client_view: dict) -> list[dict]:
    """
    CRM-style client-level interest tags (Tags[], Scope always "Client")
    — a region or industry the CLIENT has personally expressed interest
    in, independent of what the portfolio actually holds. Previously
    loaded into client_view["tags"] by data_layer and never read by
    anything downstream at all (confirmed dead data). Returned as plain
    {category, tag_type} pairs — no filtering here; market_news.py
    separately decides Industry tags are usable as news subjects while
    Region tags aren't (no evidence a region-level query returns relevant
    results), but the prompt-facing text still gets to mention both as
    client context.
    """
    tags = client_view.get("tags") or []
    return [
        {"category": tag.get("TagName"), "tag_type": tag.get("TagTypeName")}
        for tag in tags
        if isinstance(tag, dict) and tag.get("TagName")
    ]


def _priority_source_label(item: dict) -> str:
    ptype = item.get("type")
    if ptype == "violation":
        return f"Suitability violation: {item.get('description') or item.get('rule_code') or 'unspecified'}"
    if ptype == "saa_breach":
        return f"SAA deviation: {item.get('category')} ({item.get('dimension')}), breaches {item.get('breach')} bound"
    if ptype == "single_position_concentration":
        return f"Concentration flag: {clean_security_name(item.get('security_name') or '')}"
    if ptype == "high_liquidity":
        return "Liquidity attention flag (portfolio liquidity above threshold)"
    return f"Priority fact: {ptype or 'unclassified'}"


def _sources_section(
    priorities: list[dict],
    top_risk_contributors: list[dict],
    house_view_alignment: list[dict],
    market_news: list[dict],
    client_notes: list[dict],
    client_interests: list[dict],
) -> list[dict]:
    """
    A deterministic, code-built audit trail of what actually went into
    this briefing — NOT generated by the model. An LLM asked to cite its
    own sources will happily invent plausible-looking ones; every entry
    here instead comes straight from a fact already present elsewhere in
    the BriefingContext (the same v2 priority_score/fact_id provenance
    market_news.py already tracks for its own duplicate-article merging),
    so this list can never claim to have used something the briefing
    didn't actually receive.

    Each entry: {"type": str, "label": str, "url": str|None, "date":
    str|None, "fact_id": str|None} — "url" is only ever populated for a
    news article with a real link; everything else is traceable by label
    and fact_id rather than a clickable reference, since none of it has
    a natural URL.
    """
    sources: list[dict] = []

    for item in priorities:
        sources.append(
            {
                "type": "priority_fact",
                "label": _priority_source_label(item),
                "url": None,
                "date": None,
                "fact_id": item.get("fact_id"),
            }
        )

    for contributor in top_risk_contributors:
        name = contributor.get("SecurityName")
        if not name:
            continue
        sources.append(
            {
                "type": "risk_contributor",
                "label": f"Top portfolio risk contributor: {clean_security_name(name)}",
                "url": None,
                "date": None,
                "fact_id": None,
            }
        )

    if house_view_alignment:
        row = house_view_alignment[0]
        feed = "mock data" if row.get("is_mock") else (row.get("source") or "external feed")
        sources.append(
            {
                "type": "house_view",
                "label": f"Bank house view ({feed})",
                "url": None,
                "date": row.get("as_of"),
                "fact_id": None,
            }
        )

    for article in market_news:
        sources.append(
            {
                "type": "news_article",
                "label": f"{article.get('title')} ({article.get('publisher')})" if article.get("publisher") else article.get("title"),
                "url": article.get("link"),
                "date": article.get("published_at"),
                "fact_id": None,
            }
        )

    for note in client_notes:
        sources.append(
            {
                "type": "client_note",
                "label": f"CRM note: {note.get('text')}",
                "url": None,
                "date": note.get("date"),
                "fact_id": None,
            }
        )

    for interest in client_interests:
        sources.append(
            {
                "type": "client_interest_tag",
                "label": f"CRM interest tag: {interest.get('category')} ({interest.get('tag_type')})",
                "url": None,
                "date": None,
                "fact_id": None,
            }
        )

    return sources


def _attribution_caveat_section(priority_bundle: dict) -> dict:
    """
    Plain, code-computed facts about whether this portfolio's data can
    actually support attributing its value change to a specific cause —
    NOT a judgment call about what the cause is. Built from figures
    analysis_layer already computed (liquidity ratio, risk contributors,
    look-through currency exposure); nothing here is inferred or guessed.

    Exists because an LLM asked to "identify the main drivers" of a value
    change will do so even when the data doesn't support any driver at
    all — e.g. a heavily liquid/cash portfolio with no security-level risk
    contributors still losing value. Handing the model these facts
    directly (rather than making it infer "is this explainable" itself)
    is what lets prompt_builder.py's SYSTEM_PROMPT rule tell it, in a
    fact-grounded way, when to say "the cause isn't identifiable from the
    available data" instead of inventing a plausible-sounding story.
    """
    liquidity = priority_bundle.get("liquidity") or {}
    concentrations = priority_bundle.get("concentrations") or {}
    return {
        "liquidity_ratio": liquidity.get("liquidity_ratio"),
        "has_holdings_based_drivers": bool(priority_bundle.get("top_risk_contributors")),
        "non_base_currency_exposure": concentrations.get("non_base_currency_exposure"),
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
