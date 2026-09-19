"""
Regression test for a specific hallucination risk: an LLM asked to
"identify the main drivers" of a portfolio value change will do so even
when the data provides no holdings-based explanation at all — e.g. a
fully liquid (cash) portfolio that still lost value. This confirms the
attribution_caveat mechanism (context_builder.py's _attribution_caveat_section
/ prompt_builder.py's _format_attribution_caveat + SYSTEM_PROMPT rule)
actually prevents this in a REAL model call, not just in the deterministic
formatting tests in test_prompt_builder.py — a canned fake client can't
test whether the prompt itself changes model behavior.

Requires OPENAI_API_KEY (and the 'openai' package, and network access) —
skipped, not failed, otherwise, matching the REAL_DATA_AVAILABLE pattern in
test_real_data_regression.py (a plain print+return, so this also runs
cleanly under run_tests.py's non-pytest runner).

LLM output is not deterministic, so this makes exactly ONE real call per
test and checks the result for fabricated causal-attribution patterns that
must not appear when there is genuinely zero supporting data (no risk
contributors, no house-view alignment, no news, 100% liquid). A failure
here prints the model's exact, full response so a human can review the
specific fabrication rather than just seeing "test failed".
"""
import os
import re

from synthesis.briefing_generator import BriefingGenerationError, generate_briefing

OPENAI_AVAILABLE = bool(os.environ.get("OPENAI_API_KEY"))
if OPENAI_AVAILABLE:
    try:
        import openai  # noqa: F401
    except ImportError:
        OPENAI_AVAILABLE = False

SKIP_REASON = "OPENAI_API_KEY not set or 'openai' package not installed"

# Phrases that would fabricate a holdings/market-based cause. Legitimate
# only when the input actually contains a risk contributor, house-view
# divergence, or news article to back them up — the fixture below has
# none of those, by design.
_FABRICATED_CAUSE_PATTERNS = [
    r"\bdriven by\b",
    r"\bdue to (weakness|strength|volatility|market|its largest|a decline in)\b",
    r"\bbecause of (market|sector|equity|its)\b",
    r"\battributable to\b",
    r"\bas a result of (market|sector|equity)\b",
    r"\bsector (allocation|exposure|weakness)\b",
    r"\bvolatility contribution",
    r"\bits largest holding\b",
]

# At least one of these should show up when the model correctly declines
# to attribute an unexplainable change to a specific cause.
_LIMITATION_ACKNOWLEDGEMENT_TERMS = (
    "liquid", "cash", "not identifiable", "no holdings", "no security",
    "flows", "fees", "currency",
)

# A causal-connector match doesn't fabricate anything if it's actually
# negated ("is NOT attributable to...", "isn't due to...") — that's
# exactly the correct, desired hedge. Checked as plain substrings in a
# short preceding window rather than a full negation parser: cheap, and
# good enough for the connector phrases this list actually contains.
_NEGATION_MARKERS = (
    "not ", "n't", "never", "no reliable", "isn't", "aren't", "wasn't",
    "cannot", "can't", "unable to", "without a", "rather than",
)


def _find_fabricated_cause_flags(text: str, window: int = 40) -> list[tuple[str, str]]:
    """
    Returns [(pattern, matched_snippet), ...] for every _FABRICATED_CAUSE_PATTERNS
    hit in `text` (already lowercased) that ISN'T preceded by a negation
    marker within `window` characters. Extracted as its own function so the
    negation logic itself is covered by fast, deterministic unit tests
    below, independent of the live API call.
    """
    flags = []
    for pattern in _FABRICATED_CAUSE_PATTERNS:
        for m in re.finditer(pattern, text):
            preceding = text[max(0, m.start() - window):m.start()]
            if any(marker in preceding for marker in _NEGATION_MARKERS):
                continue
            snippet = text[max(0, m.start() - window):m.end() + window]
            flags.append((pattern, snippet))
    return flags


# --- fast, deterministic tests for the flagging logic itself (no network) ---


def test_flags_an_unhedged_fabricated_cause():
    text = "the decline was driven by weakness in its largest holding."
    flags = _find_fabricated_cause_flags(text)
    assert flags, "expected 'driven by' to be flagged when not negated"


def test_does_not_flag_a_correctly_negated_cause():
    # The exact real-model phrasing that originally produced a false
    # positive in this detector: "not attributable to" must NOT be
    # flagged, since it's the correct, desired hedge.
    text = "this change in value is not attributable to investment holdings."
    assert _find_fabricated_cause_flags(text) == []


def test_does_not_flag_rather_than_market_volatility():
    text = "the cause may be due to cash flows or fees rather than market volatility."
    # "due to cash flows" isn't itself a listed pattern (only specific
    # holdings/market terms after "due to" are), so this should be clean.
    assert _find_fabricated_cause_flags(text) == []


def test_flags_unnegated_attributable_to_market_move():
    text = "the loss is attributable to market weakness in the technology sector."
    flags = _find_fabricated_cause_flags(text)
    assert any(p == r"\battributable to\b" for p, _ in flags)


def _fully_liquid_declining_context() -> dict:
    """
    A synthetic BriefingContext for a portfolio that is 100% cash and lost
    5% of its value since the last observation. Nothing in this context —
    no risk contributors, no house-view divergence, no news — can
    legitimately explain the decline; any specific causal claim tied to a
    holding, sector, or market move would be fabricated.
    """
    return {
        "client": {"name": "Test Client", "risk_profile": "Conservative", "esg_profile": None},
        "portfolio": {
            "portfolio_id": 999001,
            "portfolio_name": "Cash Reserve",
            "value": 95000,
            "reporting_currency": "CHF",
            "performance_trend": {
                "latest_value": 95000,
                "previous_value": 100000,
                "change_since_previous_point": -5000,
                "change_since_previous_point_pct": -0.05,
                "latest_date": "2026-08-01",
                "previous_date": "2026-07-01",
            },
        },
        "priorities": [
            {
                "type": "high_liquidity",
                "severity": "Info",
                "priority_score": 60.0,
                "liquidity_ratio": 1.0,
                "threshold": 0.10,
                "liquidity": 95000,
                "aum": 95000,
            }
        ],
        "top_risk_contributors": [],
        "change_since_last_interaction": {
            "source": "state_diff",
            "is_first_interaction": True,
            "details": {},
        },
        "house_view_alignment": [],
        "market_news": [],
        "market_news_status": {"status": "no_news_found", "reasons": ["no_search_terms_generated"]},
        "attribution_caveat": {
            "liquidity_ratio": 1.0,
            "has_holdings_based_drivers": False,
            "non_base_currency_exposure": 0.0,
        },
    }


def test_fully_liquid_decline_does_not_fabricate_a_holdings_based_cause():
    if not OPENAI_AVAILABLE:
        print(f"SKIPPED: {SKIP_REASON}")
        return

    context = _fully_liquid_declining_context()
    try:
        briefing = generate_briefing(context)
    except BriefingGenerationError as e:
        print(f"SKIPPED: live API call failed ({e}) — not a hallucination-detection result either way")
        return

    combined_lower = " ".join(
        briefing[key] for key in ("recent_development", "health_check", "outlook_and_actions")
    ).lower()

    flagged = _find_fabricated_cause_flags(combined_lower)
    assert not flagged, (
        "Model attributed the value change to a holdings/market-based cause with "
        "ZERO supporting data (no risk contributors, no house-view alignment, no "
        f"news, 100% liquid). Flagged snippet(s) for review: {flagged}\n\n"
        f"Full response for review:\nrecent_development: {briefing['recent_development']}\n\n"
        f"health_check: {briefing['health_check']}\n\n"
        f"outlook_and_actions: {briefing['outlook_and_actions']}"
    )

    acknowledges_limitation = any(term in combined_lower for term in _LIMITATION_ACKNOWLEDGEMENT_TERMS)
    assert acknowledges_limitation, (
        "Model neither fabricated a recognized causal pattern NOR acknowledged the "
        "data limitation (liquidity/cash/flows/fees/currency) — expected at least "
        "the latter, since this portfolio's data provides no legitimate causal "
        f"explanation for the decline.\n\nFull response for review:\n{briefing['recent_development']}"
    )
