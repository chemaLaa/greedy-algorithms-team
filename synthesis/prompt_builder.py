"""
Turns a BriefingContext (synthesis.context_builder output) into the
actual prompt sent to the model.

The core design problem this file solves: if you just serialize the
context as JSON and paste it into the prompt, the model tends to narrate
the data structure back ("the priorities list contains...") instead of
synthesizing a story — exactly what the case brief says NOT to do ("a
briefing that explains... rather than three separate data summaries").

So this module has two distinct jobs, split into two testable functions:
  1. context_to_prose() — convert structured facts into readable, labeled
     text fragments FIRST (no LLM call, fully deterministic, fully
     tested without a network or a model).
  2. build_prompt() — wrap those fragments with the fixed instructions
     (the 4 required questions, the 3 required sections, the "one
     narrative not stitched summaries" constraint) into the actual
     {system, messages} the model call uses.
"""
from __future__ import annotations

from typing import Optional

from enrichment.market_news import clean_security_name

SYSTEM_PROMPT = """\
You are an AI briefing assistant inside URO Advisor Pro, a wealth-advisory \
platform. A wealth manager is about to call or meet a client, often on \
short notice, and needs to walk in already understanding the situation.

You will be given facts about one client's portfolio: recent performance, \
current risks and compliance issues, how the portfolio compares to the \
bank's tactical house view, relevant market news, and what has changed \
since the advisor last looked at this client. All of these facts are \
labeled by source in the message below.

Your job is to write ONE coherent briefing that an advisor can read in \
about 60 seconds (roughly 150-220 words total). It must answer, in this \
order, across exactly three sections:

1. "recent_development" — What happened? Summarize the portfolio's recent \
   development and identify its main drivers, connecting portfolio facts, \
   market context, and client circumstances into a single narrative rather \
   than listing them as separate summaries from different sources.
2. "health_check" — What is the current situation? Cover allocation \
   deviations, risks, compliance/suitability issues, and concentration — \
   whatever genuinely deserves the advisor's attention right now.
3. "outlook_and_actions" — What could happen next, and what should the \
   advisor do? Connect the portfolio to relevant market developments and \
   the bank's house view where relevant, then propose concrete, specific \
   next-best actions the advisor could raise on the call.

Critical rules:
- Write ONE connected story, not three isolated summaries. A later section \
  may reference something raised in an earlier one.
- The facts you're given are already labeled with a severity/rank, but \
  that ranking is a simple rule-based sort (compliance severity, then \
  everything else), not a judgment about what actually matters most for \
  THIS client's conversation. Use your own judgment about relative \
  importance — do not just narrate the list in the order given.
- Ground every claim in the facts provided. Never invent a number, event, \
  or news detail that wasn't given to you. If information is limited (a \
  first-ever briefing for this client, no relevant news found), say so \
  briefly rather than filling the gap with something plausible-sounding.
- Write in fluent English throughout, even where a source fact was in \
  German — translate rather than mixing languages in your output.
- Plain prose, no markdown headers or bullet lists inside each section.

Respond with a JSON object with exactly these three string keys: \
"recent_development", "health_check", "outlook_and_actions". No other \
keys, no text outside the JSON object.\
"""


def context_to_prose(context: dict) -> dict[str, str]:
    """
    Converts each part of a BriefingContext into a readable text
    fragment. Pure formatting, no model call — every fragment here is
    deterministic and independently testable.
    """
    return {
        "client_and_portfolio": _format_client_and_portfolio(context),
        "performance": _format_performance(context["portfolio"].get("performance_trend")),
        "priorities": _format_priorities(context.get("priorities", [])),
        "risk_contributors": _format_risk_contributors(context.get("top_risk_contributors", [])),
        "change_since_last_interaction": _format_change(context.get("change_since_last_interaction")),
        "house_view": _format_house_view(context.get("house_view_alignment", [])),
        "news": _format_news(context.get("market_news", [])),
    }


def build_prompt(context: dict) -> dict:
    """
    Returns {"system": str, "messages": [{"role": "user", "content": str}]}
    — ready to pass to a model call. See briefing_generator.py for the
    actual API call.
    """
    fragments = context_to_prose(context)

    user_message = (
        f"{fragments['client_and_portfolio']}\n\n"
        f"RECENT PERFORMANCE:\n{fragments['performance']}\n\n"
        f"CURRENT ISSUES AND RISKS (ranked by rule-based severity, not necessarily by "
        f"real-world importance — use your own judgment):\n{fragments['priorities']}\n\n"
        f"TOP CONTRIBUTORS TO PORTFOLIO RISK:\n{fragments['risk_contributors']}\n\n"
        f"WHAT'S CHANGED SINCE THE LAST INTERACTION:\n{fragments['change_since_last_interaction']}\n\n"
        f"BANK HOUSE VIEW COMPARISON:\n{fragments['house_view']}\n\n"
        f"RELEVANT MARKET NEWS:\n{fragments['news']}\n\n"
        f"Write the briefing now, following all instructions above."
    )

    return {"system": SYSTEM_PROMPT, "messages": [{"role": "user", "content": user_message}]}


# --- formatting helpers, each independently testable ---


def _format_client_and_portfolio(context: dict) -> str:
    client = context.get("client", {})
    portfolio = context.get("portfolio", {})

    name = client.get("name") or "Unknown client"
    risk_profile = client.get("risk_profile")
    esg_profile = client.get("esg_profile")

    client_line = f"Client: {name}"
    if risk_profile:
        client_line += f" (risk profile: {risk_profile})"
    if esg_profile:
        client_line += f", ESG preference: {esg_profile}"
    client_line += "."

    portfolio_name = portfolio.get("portfolio_name") or "portfolio"
    value = portfolio.get("value")
    currency = portfolio.get("reporting_currency") or ""
    if value is not None:
        portfolio_line = f"Portfolio: {portfolio_name}, current value {value:,.0f} {currency}."
    else:
        portfolio_line = f"Portfolio: {portfolio_name} (current value unavailable)."

    return f"{client_line}\n{portfolio_line}"


def _format_performance(trend: Optional[dict]) -> str:
    if not trend or trend.get("change_since_previous_point") is None:
        return "No prior performance history available for comparison."

    latest = trend.get("latest_value")
    previous = trend.get("previous_value")
    change_pct = trend.get("change_since_previous_point_pct")
    latest_date = trend.get("latest_date")
    previous_date = trend.get("previous_date")

    change_str = f"{change_pct:+.1%}" if change_pct is not None else "an unknown amount"
    return (
        f"Portfolio value moved from {previous:,.0f} to {latest:,.0f} "
        f"({change_str}) between {previous_date} and {latest_date}."
    )


def _format_priorities(priorities: list[dict]) -> str:
    if not priorities:
        return "No active compliance issues, allocation breaches, or concentration flags."

    lines = []
    for item in priorities:
        if item["type"] == "violation":
            lines.append(f"- [{item.get('severity')}] {item.get('description')}")
        elif item["type"] == "saa_deviation":
            actual = item.get("actual")
            target = item.get("target")
            breach = item.get("breach")
            direction = "below" if breach == "min" else "above"
            lines.append(
                f"- {item.get('category')} ({item.get('dimension')}) is "
                f"{actual:.1%} of the portfolio vs. a {target:.1%} target — {direction} the allowed range."
            )
        elif item["type"] == "concentration":
            lines.append(
                f"- {clean_security_name(item.get('security_name', ''))} makes up "
                f"{item.get('weight'):.1%} of the portfolio — a concentrated single position."
            )
    return "\n".join(lines)


def _format_risk_contributors(contributors: list[dict]) -> str:
    if not contributors:
        return "No risk-contribution data available."

    lines = []
    for c in contributors:
        share = c.get("share_of_portfolio_volatility")
        share_str = f"{share:.0%}" if share is not None else "an unknown share"
        name = clean_security_name(c.get("SecurityName", ""))
        lines.append(f"- {name}: {share_str} of portfolio risk (volatility contribution).")
    return "\n".join(lines)


def _format_change(change: Optional[dict]) -> str:
    if not change:
        return "No information available about changes since the last interaction."

    source = change.get("source")
    details = change.get("details") or {}

    if source == "state_diff":
        return _format_state_diff(details)

    return _format_note_proxy(details)


def _format_state_diff(diff: dict) -> str:
    if diff.get("is_first_interaction"):
        return "This is the first briefing ever generated for this client — no prior state to compare against."

    lines = []

    value_change = diff.get("portfolio_value_change")
    if value_change and value_change.get("change_pct") is not None:
        lines.append(
            f"Portfolio value changed {value_change['change_pct']:+.1%} "
            f"(from {value_change['then']:,.0f} to {value_change['now']:,.0f}) since the last briefing."
        )

    new_violations = diff.get("violations_new") or []
    if new_violations:
        lines.append(f"New issues since last time: {', '.join(new_violations)}.")

    resolved_violations = diff.get("violations_resolved") or []
    if resolved_violations:
        lines.append(f"Resolved since last time: {', '.join(resolved_violations)}.")

    allocation_changes = diff.get("allocation_changes") or {}
    for dimension, changes in allocation_changes.items():
        for category, move in changes.items():
            lines.append(
                f"{category} ({dimension}) moved {move['change']:+.1%} since the last briefing."
            )

    position_changes = diff.get("position_changes") or {}
    for pos in position_changes.get("entered_top", []):
        lines.append(f"{pos['SecurityName']} newly entered the portfolio's top positions.")
    for pos in position_changes.get("exited_top", []):
        lines.append(f"{pos['SecurityName']} dropped out of the portfolio's top positions.")

    if not lines:
        return "No material changes detected since the last briefing for this client."

    return "\n".join(f"- {line}" for line in lines)


def _format_note_proxy(details: dict) -> str:
    since_date = details.get("since_date")
    value_then = details.get("value_then")
    change_pct = details.get("change_pct")

    if since_date is None or value_then is None:
        return "No reliable comparison point available for change since the last interaction."

    change_str = f"{change_pct:+.1%}" if change_pct is not None else "an unknown amount"
    return (
        f"Approximate estimate only (based on the client's last recorded note, {since_date}, "
        f"not an exact prior briefing state): portfolio value changed {change_str} since then."
    )


def _format_house_view(alignment: list[dict], max_actionable: int = 5) -> str:
    """
    Leads with what's actually actionable (underexposed/overexposed —
    where the client diverges from the bank's tactical call) and
    compresses "aligned" items into one summary line rather than listing
    each individually. Without this, a portfolio with many SAA categories
    can produce a house-view section longer than the rest of the prompt
    combined, for mostly "nothing to act on here" content — exactly the
    kind of noise a 60-second-target briefing shouldn't have to filter
    out itself.
    """
    actionable = [
        item for item in alignment if item.get("relative_position") in ("underexposed", "overexposed")
    ][:max_actionable]
    aligned = [item for item in alignment if item.get("relative_position") == "aligned"]

    if not actionable and not aligned:
        return "No notable alignment or divergence from the bank's current house view."

    lines = []
    for item in actionable:
        lines.append(
            f"- {item.get('category')} ({item.get('dimension')}): the bank is "
            f"{item.get('house_view_stance')} — client is currently {item.get('relative_position')} "
            f"relative to this view (client actual {item.get('client_actual'):.1%} vs. "
            f"target {item.get('client_target'):.1%}). Rationale: {item.get('rationale')}"
        )

    if aligned:
        categories = ", ".join(item["category"] for item in aligned)
        lines.append(f"- Already aligned with the house view on: {categories}.")

    return "\n".join(lines)


def _format_news(articles: list[dict]) -> str:
    if not articles:
        return "No relevant market news found for this portfolio's holdings."

    lines = []
    for article in articles:
        lines.append(
            f"- \"{article.get('title')}\" ({article.get('publisher')}) — relevant to "
            f"{article.get('matched_query')} ({article.get('match_reason')})."
        )
    return "\n".join(lines)