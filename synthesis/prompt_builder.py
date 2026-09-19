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

from enrichment.house_view import HOUSE_VIEW_PRECEDENCE_NOTE
from enrichment.market_news import clean_security_name

SYSTEM_PROMPT = """\
You are an AI briefing assistant inside URO Advisor Pro, a wealth-advisory \
platform. A wealth manager is about to call or meet a client, often on \
short notice, and needs to walk in already understanding the situation.

You will be given facts about one client's portfolio: recent performance, \
current risks and compliance issues, how the portfolio compares to the \
bank's tactical house view, relevant market news, notes an advisor has \
recorded about this client's own circumstances and preferences, and what \
has changed since the advisor last looked at this client. All of these \
facts are labeled by source in the message below.

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
- Only attribute a change in portfolio value to a specific cause (a \
  holding, a sector, a market move) when the facts you were given actually \
  support that link. The "DATA AVAILABILITY FOR ATTRIBUTING THIS CHANGE" \
  section tells you directly when holdings-based data is thin or absent — \
  e.g. a heavily liquid/cash portfolio, or no security-level risk \
  contributors at all. When the value change isn't explained by the data \
  provided, say plainly that the cause isn't identifiable from the \
  available data and recommend the advisor check cash flows, fees, and \
  currency movements with the client, rather than inventing a \
  plausible-sounding explanation. A portfolio's "top contributors to \
  portfolio risk" are ranked by their contribution to volatility (a \
  forward-looking risk measure) — they are NOT a confirmed explanation of \
  what actually drove the recent value change, and must not be presented \
  as one unless another fact you were given actually supports that \
  specific link.
- "CLIENT NOTES / CIRCUMSTANCES" are an advisor's own free-text \
  observations about this specific client — preferences, exclusions, \
  life events, personality — not portfolio data. Treat a stated \
  preference or exclusion (e.g. "no fossil fuel positions", "wants a \
  cash reserve on hand") as something the rest of the briefing should \
  respect or reference where relevant, not as a fact to just repeat. \
  Notes carry a date; use judgment about whether an old note still \
  applies rather than presenting it as current fact, and never invent a \
  circumstance beyond what a note actually says.
- The "CLIENT'S OWN STATED INTERESTS" are CRM tags recording what the \
  client is personally interested in — they are NOT a portfolio holding \
  and NOT confirmed exposure. Never describe an interest tag as \
  something the client "holds" or "is invested in"; if news happens to \
  match one, frame it as relevant to the client's stated interest, not \
  as commentary on an actual position.
- "BANK'S CURRENT EXPECTED RETURN" is the bank's own live risk-engine \
  estimate — present it as the bank's current estimate (e.g. "the \
  bank's risk engine currently estimates..."), never as a promise or \
  guarantee of future results, and never blend it into your account of \
  what already happened. It is a distinct, forward-looking figure, not \
  something derived from or confirming the historical performance \
  numbers elsewhere in this message — do not present the two as if one \
  explains the other unless another fact you were given actually \
  supports that link. If it isn't available for this portfolio, say so \
  rather than omitting any mention of it or estimating one yourself.
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
        "client_notes": _format_client_notes(context.get("client_notes", [])),
        "client_interests": _format_client_interests(context.get("client_interests", [])),
        "performance": _format_performance(context["portfolio"].get("performance_trend")),
        "current_risk_return": _format_current_risk_return(context.get("current_risk_return")),
        "attribution_caveat": _format_attribution_caveat(context.get("attribution_caveat")),
        "priorities": _format_priorities(context.get("priorities", [])),
        "risk_contributors": _format_risk_contributors(context.get("top_risk_contributors", [])),
        "change_since_last_interaction": _format_change(context.get("change_since_last_interaction")),
        "house_view": _format_house_view(context.get("house_view_alignment", [])),
        "news": _format_news(context.get("market_news", []), context.get("market_news_status")),
        "watch_for": _format_watch_for(context.get("watch_for")),
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
        f"CLIENT NOTES / CIRCUMSTANCES (from CRM, most recent first):\n{fragments['client_notes']}\n\n"
        f"CLIENT'S OWN STATED INTERESTS (CRM tags — personal interest, NOT necessarily a portfolio "
        f"holding):\n{fragments['client_interests']}\n\n"
        f"RECENT PERFORMANCE:\n{fragments['performance']}\n\n"
        f"BANK'S CURRENT EXPECTED RETURN (forward-looking risk-engine estimate, NOT a guarantee and NOT "
        f"derived from the historical performance above):\n{fragments['current_risk_return']}\n\n"
        f"DATA AVAILABILITY FOR ATTRIBUTING THIS CHANGE:\n{fragments['attribution_caveat']}\n\n"
        f"CURRENT ISSUES AND RISKS (ranked by rule-based severity, not necessarily by "
        f"real-world importance — use your own judgment):\n{fragments['priorities']}\n\n"
        f"TOP CONTRIBUTORS TO PORTFOLIO RISK:\n{fragments['risk_contributors']}\n\n"
        f"WHAT'S CHANGED SINCE THE LAST INTERACTION:\n{fragments['change_since_last_interaction']}\n\n"
        f"BANK HOUSE VIEW COMPARISON:\n{fragments['house_view']}\n\n"
        f"RELEVANT MARKET NEWS:\n{fragments['news']}\n\n"
        f"WATCH FOR (single-factor approximation):\n{fragments['watch_for']}\n\n"
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


def _format_client_notes(notes: list[dict]) -> str:
    """
    CRM-style advisory notes (synthesis.context_builder's client_notes),
    most-recent-first. This is the ONE place a client's own recorded
    circumstances/preferences/exclusions reach the model as content, not
    just as a date used elsewhere for interaction-recency — see
    context_builder._client_notes_section for why that content was
    previously dropped entirely.
    """
    if not notes:
        return "No advisory notes on file for this client."

    lines = []
    for note in notes:
        date = note.get("date")
        date_str = date.split("T")[0] if isinstance(date, str) and "T" in date else (date or "unknown date")
        lines.append(f"- ({date_str}) {note.get('text')}")
    return "\n".join(lines)


def _format_client_interests(interests: list[dict]) -> str:
    """
    CRM-level interest tags (synthesis.context_builder's client_interests)
    — a region or industry the client has personally expressed interest
    in, independent of what the portfolio actually holds. Labeled
    explicitly as "personal interest, not a holding" both here and in the
    prompt section header, so a model doesn't accidentally narrate one as
    if it were a position in the portfolio.
    """
    if not interests:
        return "No client interest tags on file."
    return ", ".join(f"{item.get('category')} ({item.get('tag_type')})" for item in interests)


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


def _format_current_risk_return(snapshot: Optional[dict]) -> str:
    """
    The bank's own live risk-engine snapshot (synthesis.context_builder's
    current_risk_return, from analysis_layer.performance's
    current_risk_return_snapshot()) — the ONE genuinely forward-looking
    figure in this whole prompt, as opposed to everything else here,
    which describes what already happened.

    Never silently defaults: an "unavailable" status (or a bundle that
    never had this data at all) is stated plainly rather than presenting
    a stale number or omitting the section without explanation — the
    model should know the bank's own expected-return estimate isn't
    available for this portfolio, not just see the section vanish.
    """
    if not snapshot or snapshot.get("status") in (None, "unavailable"):
        return "Not available for this portfolio."

    expected_return = snapshot.get("expected_return")
    volatility = snapshot.get("volatility")
    value_at_risk = snapshot.get("value_at_risk")

    parts = []
    if expected_return is not None:
        parts.append(f"expected return {expected_return:+.1%} (forward-looking risk-engine estimate, not a guarantee)")
    if volatility is not None:
        parts.append(f"current volatility {volatility:.1%}")
    if value_at_risk is not None:
        parts.append(f"value-at-risk {value_at_risk:.1%}")

    if not parts:
        return "Not available for this portfolio."

    prefix = "Partial data — " if snapshot.get("status") == "partial" else ""
    return prefix + "; ".join(parts) + "."


def _format_attribution_caveat(caveat: Optional[dict]) -> str:
    """
    Surfaces, as an explicit fact rather than something the model has to
    infer, whether this portfolio's data can actually support blaming its
    value change on a specific cause. Always returns something (never an
    empty string) so this section never silently disappears from the
    prompt.
    """
    if not caveat:
        return "No data-availability information provided for this portfolio."

    lines = []

    liquidity_ratio = caveat.get("liquidity_ratio")
    if liquidity_ratio is not None and liquidity_ratio >= 0.5:
        lines.append(
            f"- {liquidity_ratio:.0%} of this portfolio's AUM is currently liquid (cash) — "
            f"a value change of this size may not be attributable to security holdings at all."
        )

    if not caveat.get("has_holdings_based_drivers"):
        lines.append(
            "- No security-level risk-contribution data is available for this portfolio. "
            "Do not attribute the value change to a specific holding, sector, or market move "
            "unless another fact below actually supports that link."
        )

    fx_exposure = caveat.get("non_base_currency_exposure")
    if fx_exposure is not None and fx_exposure >= 0.3:
        lines.append(
            f"- {fx_exposure:.0%} of this portfolio's weight is held in a currency other than "
            f"its own reporting currency. Currency movements are a plausible unexplained factor, "
            f"but this dataset has no FX-rate history — do not estimate or state a specific FX "
            f"contribution, only note currency movements as a possible factor worth the advisor "
            f"checking."
        )

    if not lines:
        return "No specific data-availability caveats for this portfolio's performance attribution."

    return "\n".join(lines)


def _format_priorities(priorities: list[dict]) -> str:
    if not priorities:
        return "No active compliance issues, allocation breaches, or concentration flags."

    lines = []
    for item in priorities:
        if item["type"] == "violation":
            lines.append(f"- [{item.get('severity')}] {item.get('description')}")
        elif item["type"] == "saa_breach":
            actual = item.get("actual")
            target = item.get("target")
            breach = item.get("breach")
            direction = "below" if breach == "min" else "above"
            lines.append(
                f"- {item.get('category')} ({item.get('dimension')}) is "
                f"{actual:.1%} of the portfolio vs. a {target:.1%} target — {direction} the allowed range."
            )
        elif item["type"] == "single_position_concentration":
            lines.append(
                f"- {clean_security_name(item.get('security_name', ''))} makes up "
                f"{item.get('weight'):.1%} of the portfolio — a concentrated single position."
            )
        elif item["type"] == "high_liquidity":
            ratio = item.get("liquidity_ratio")
            ratio_str = f"{ratio:.1%}" if ratio is not None else "above 10%"
            lines.append(f"- Portfolio liquidity is {ratio_str} of AUM — may warrant discussion.")
    return "\n".join(lines)


def _format_risk_contributors(contributors: list[dict]) -> str:
    if not contributors:
        return "No risk-contribution data available."

    lines = [
        "(Forward-looking risk/volatility contribution, not a confirmed explanation of the "
        "recent value change — do not present these as the cause of recent performance unless "
        "another fact supports that specific link.)"
    ]
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
    Always opens with HOUSE_VIEW_PRECEDENCE_NOTE — this is the ONE place
    that sentence reaches the model's actual input text, regardless of
    whether there's anything else to say about the house view at all.
    Without that, "suitability/SAA takes precedence over the house view"
    would only ever be an internal assumption this code makes, never
    something the model is actually told.

    Then leads with what's actually actionable ("opposite" — where the
    client's position tilts away from the bank's tactical call) and
    compresses "aligned" and "at_target" items into one summary line each
    rather than listing every category individually. Without this, a
    portfolio with many SAA categories can produce a house-view section
    longer than the rest of the prompt combined, for mostly "nothing to
    act on here" content — exactly the kind of noise a 60-second-target
    briefing shouldn't have to filter out itself.

    "aligned" and "at_target" are kept as two separate summary lines, not
    merged into one: being at_target means the client hasn't acted on the
    house view's tactical call in either direction, which is a distinct
    fact from actually being tilted the same way the bank recommends.
    """
    lines = [HOUSE_VIEW_PRECEDENCE_NOTE]

    opposite = [item for item in alignment if item.get("relative_position") == "opposite"][:max_actionable]
    aligned = [item for item in alignment if item.get("relative_position") == "aligned"]
    at_target = [item for item in alignment if item.get("relative_position") == "at_target"]

    if not opposite and not aligned and not at_target:
        lines.append("No notable alignment or divergence from the bank's current house view.")
    else:
        for item in opposite:
            lines.append(
                f"- {item.get('category')} ({item.get('dimension')}): the bank is "
                f"{item.get('house_view_stance')} — client is currently positioned opposite this "
                f"view (client actual {item.get('client_actual'):.1%} vs. "
                f"target {item.get('client_target'):.1%}). Rationale: {item.get('rationale')}"
            )

        if aligned:
            categories = ", ".join(item["category"] for item in aligned)
            lines.append(f"- Already aligned with the house view on: {categories}.")

        if at_target:
            categories = ", ".join(item["category"] for item in at_target)
            lines.append(
                f"- Exactly at the client's own SAA target, no tactical tilt in either "
                f"direction yet, for: {categories}."
            )

    if any(item.get("is_mock") for item in alignment):
        lines.append("(This house view is MOCK data for demonstration purposes, not a real bank publication.)")

    return "\n".join(lines)


def _format_watch_for(watch_for: Optional[dict]) -> str:
    """
    Formats the watch_for section (correlation/shock_propagation +
    state/counterfactual output) for inclusion in the model prompt.

    Always prepends the single-factor approximation caveat so the model
    never treats the CHF impact figure as a reliable forecast.
    """
    caveat = (
        "NOTE: The following is a linear single-factor approximation only "
        "— not a guarantee or a multi-factor forecast."
    )

    if watch_for is None:
        return f"{caveat}\nNo factor-relevant finding to report."

    factor = watch_for.get("factor") or "unknown"
    shock = watch_for.get("shock") or {}
    pattern = watch_for.get("pattern_history") or {}

    shock_pct = shock.get("shock_pct")
    exposure = shock.get("exposure")
    chf_impact = shock.get("chf_impact")

    shock_pct_str = f"{shock_pct:+.0%}" if shock_pct is not None else "N/A"
    exposure_str = f"{exposure:.1%}" if exposure is not None else "N/A"
    chf_impact_str = f"CHF {chf_impact:+,.0f}" if chf_impact is not None else "unavailable"

    occurrences = pattern.get("occurrences", 0)
    if occurrences > 0:
        history_str = f"This signal has appeared {occurrences} time{'s' if occurrences != 1 else ''} in prior snapshots."
    else:
        history_str = "No prior history in available snapshots."

    return (
        f"{caveat}\n"
        f"Factor: {factor} | Shock size: {shock_pct_str} | "
        f"Portfolio exposure: {exposure_str} | Estimated CHF impact: {chf_impact_str}\n"
        f"Pattern history: {history_str}"
    )


def _format_news(articles: list[dict], status: Optional[dict] = None) -> str:
    """
    `status` (enrichment.market_news.fetch_relevant_news_bundle() output,
    or context_builder's best-effort equivalent) lets this distinguish a
    genuine search failure from a real "nothing found" result — these
    must never collapse into the same sentence, or the model could narrate
    a fetch failure as if the market were simply quiet.
    """
    if status and status.get("status") == "fetch_failed":
        return (
            "Market news search could not be completed (a provider or network error occurred). "
            "This is NOT the same as finding no relevant news — do not state or imply that no "
            "news exists; say the search itself failed."
        )

    if not articles:
        return "No relevant market news found for this portfolio's holdings."

    lines = []
    for article in articles:
        queries = article.get("matched_queries")
        if queries is None:
            queries = [article["matched_query"]] if article.get("matched_query") else []
        reasons = article.get("match_reasons")
        if reasons is None:
            reasons = [article["match_reason"]] if article.get("match_reason") else []

        query_str = ", ".join(q for q in queries if q) or "the portfolio"
        reason_str = "; ".join(r for r in reasons if r) or "relevant to portfolio holdings"
        lines.append(
            f"- \"{article.get('title')}\" ({article.get('publisher')}) — relevant to "
            f"{query_str} ({reason_str})."
        )
    return "\n".join(lines)