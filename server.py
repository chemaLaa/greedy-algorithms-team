"""
FastAPI server: serves the demo front end at / and exposes
POST /api/briefing for the "Generate Briefing" button.

Run:
    pip install fastapi uvicorn
    export ANTHROPIC_API_KEY=sk-ant-...
    python -m uvicorn server:app --reload --port 8000

Then open: http://localhost:8000/
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Literal, Optional

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ValidationError

from data_layer import load_clients, load_reference, ReferenceIndex, build_client_view
from analysis_layer import build_client_priorities
from state import refresh_client_state
from enrichment.house_view import compare_portfolio_to_house_view
from synthesis.context_builder import build_briefing_context
from synthesis.prompt_builder import context_to_prose
from synthesis.briefing_generator import (
    BriefingGenerationError,
    DEFAULT_MODEL,
    _default_client,
    _extract_text,
    _parse_json_response,
)

# ── configuration ─────────────────────────────────────────────────────────
CLIENTS_PATH = os.environ.get("CLIENTS_PATH", "data/core-case/portfolio-data/clients.json")
REFERENCE_PATH = os.environ.get("REFERENCE_PATH", "data/core-case/portfolio-data/reference.json")
BRIEFING_MODEL = os.environ.get("BRIEFING_MODEL", DEFAULT_MODEL)
STATE_DIR = Path(".state")

# ── load data once at startup ─────────────────────────────────────────────
_clients: list[dict] = load_clients(CLIENTS_PATH)
_ref: ReferenceIndex = ReferenceIndex(load_reference(REFERENCE_PATH))
_client_by_id: dict[str, dict] = {str(c.get("ClientId")): c for c in _clients}

# ── in-memory result cache: (client_id, portfolio_id) → response dict ────
_cache: dict[tuple, dict] = {}

app = FastAPI(title="URO Advisor Pro — Briefing API")


# ── /api/clients ───────────────────────────────────────────────────────────
@app.get("/api/clients")
def list_clients() -> list[dict]:
    rows = []
    for c in _clients:
        cid  = str(c.get("ClientId"))
        is_company = c.get("IsClientACompany", False)
        name = (
            c.get("Company") or
            f"{c.get('FirstName', '')} {c.get('LastName', '')}".strip()
        )
        portfolios = [
            {"id": str(p["PortfolioId"]), "name": p.get("Name", "")}
            for p in c.get("Portfolios", [])
        ]
        rows.append({"id": cid, "name": name, "type": "Company" if is_company else "Individual",
                     "portfolios": portfolios})
    rows.sort(key=lambda r: r["name"].lower())
    return rows


# ── Pydantic models ────────────────────────────────────────────────────────
class BriefingRequest(BaseModel):
    client_id: str
    portfolio_id: Optional[str] = None
    scope: Literal["client", "portfolio"] = "client"


class AttentionItem(BaseModel):
    level: Literal["critical", "warning", "info"]
    title: str
    detail: str
    source: str


class ClientInfo(BaseModel):
    name: str
    id: str
    type: str
    profile: str
    assets_chf: str
    age: Optional[int] = None


class SourceRef(BaseModel):
    section: str   # human-readable section name, e.g. "Suitability violations"
    field: str     # data field / path it came from, e.g. "active_violations"
    detail: str    # what was in it, e.g. "13 active — 7 Error, 6 Warning"


class ReadOutput(BaseModel):
    text: str
    cites: list[str]


class BriefingResponse(BaseModel):
    client: ClientInfo
    headline: str
    attention: list[AttentionItem]
    since_last: list[str]
    talking_points: list[str]
    read: ReadOutput
    sources: list[SourceRef]


class _ModelOutput(BaseModel):
    """Validates the five keys the model must return (client info added server-side)."""
    headline: str
    attention: list[AttentionItem]
    since_last: list[str]
    talking_points: list[str]
    read: ReadOutput


# ── system prompt for the /api/briefing shape ─────────────────────────────
_SYSTEM = """\
You are an AI briefing assistant for URO Advisor Pro, a wealth-management platform.
Produce a structured JSON briefing for a wealth advisor preparing for a client call.

Return exactly one valid JSON object with these five keys:
  "headline"       : one sentence (max 20 words) — the single most important thing right now
  "attention"      : array of 2-4 objects, each with:
                       "level"  : "critical", "warning", or "info"
                       "title"  : short label, max 6 words — MUST contain a number, %, or CHF amount
                       "detail" : one sentence explaining the issue — MUST contain a number, %, or CHF amount
                       "source" : short human-readable label the advisor would recognise
                                  (e.g. "Suitability violations", "SAA allocation", "Risk contributors")
                                  — NOT an internal field name or camelCase identifier
  "since_last"     : array of 0-4 short strings — concrete changes since the last interaction;
                     each entry MUST contain a date (YYYY-MM-DD or month name), a CHF amount,
                     or a non-zero % or pp change (e.g. "+3.7%", "-14 pp");
                     if nothing material changed (including a 0.0% value move), return []
  "talking_points" : array of 3-5 short strings — specific actionable points to raise on the call;
                     each MUST include a number, percentage, or named position/security;
                     MUST NOT start with Consider, Discuss, Evaluate, Review, or Look into
  "read"           : object with two keys — a short synthesis paragraph and citations:
                       "text"  : string, under 150 words — one coherent synthesis paragraph
                       "cites" : array of 1-3 short strings naming the facts being connected

READ rules (hard constraints for "read.text"):
- NUMBER-ANCHORING: every number in "text" must already appear in one of the other sections
  above (headline, attention, since_last, talking_points). Never compute a new number.
- Sentence 1: name ONE structural link between two facts from different sections above
  (e.g. a risk contributor is also the source of an SAA breach).
- Sentences 2-3: state what to watch for, using only the WATCH FOR section provided —
  restate the factor, shock size, and CHF impact as given; do not alter or invent figures.
- Use "could", "would", "if this continues" — NEVER "will" (unless "will not").
- Never present the bank's ExpectedReturn as your own conclusion; if cited, attribute it to the bank.
- If no genuine link exists between two facts, say so plainly rather than manufacturing one.

Rules — follow exactly:
- Use ONLY the data provided. Never invent a number, security name, date, or event.
- Severity ordering: if any Error-level suitability violations are present, they MUST appear first in
  attention and the headline MUST reference them. Never let concentration or allocation drift outrank
  an active Error-level compliance breach.
- Merge related findings into one attention item rather than listing them separately; maximum 4 items.
- No vague words (significant, heavy, substantial, major, considerable) without a number within 6 words.
- Total output length (headline + attention + since_last + talking_points combined) must be under 150 words.
- Keep all strings concise; the advisor has 60 seconds to read this.
- Output JSON only. No text before or after the object. No markdown code fences.
- This prompt contains the word JSON, which activates JSON-only output mode.
"""


_DIGIT_RE = re.compile(r"\d")
_DATE_OR_AMOUNT_RE = re.compile(
    r"\d{4}-\d{2}-\d{2}"                          # ISO date
    r"|January|February|March|April|May|June"
    r"|July|August|September|October|November|December"   # month name
    r"|CHF\s*[\d,]"                                # CHF amount
    r"|[+-]?[1-9]\d*\.?\d*\s*%"                   # non-zero % change (e.g. +3.7%, -5.3%)
    r"|[+-]?[1-9]\d*\s*pp",                        # pp deviation
    re.IGNORECASE,
)
_ZERO_CHANGE_RE = re.compile(r"\+0\.0%|0\.0\s*%|\b0\s*pp\b", re.IGNORECASE)
_VAGUE_RE = re.compile(
    r"\b(significant(?:ly)?|heavy|heavily|substantial(?:ly)?|major|considerable)\b",
    re.IGNORECASE,
)


def _check_output(out: dict) -> list[str]:
    """
    Post-generation quality gate. Returns a list of violation strings;
    empty list means the output is acceptable. Caller retries on any failure.
    """
    issues: list[str] = []

    # since_last: empty list is fine; each entry must carry a real anchor
    # (date, month, CHF amount, or non-zero %/pp change).
    # A 0.0% value-change entry is useless and must be suppressed by the model.
    for i, entry in enumerate(out.get("since_last") or []):
        if _ZERO_CHANGE_RE.search(entry):
            issues.append(f"since_last[{i}] reports a zero change — return [] instead: {entry!r}")
        elif not _DATE_OR_AMOUNT_RE.search(entry):
            issues.append(f"since_last[{i}] has no date, CHF, or non-zero % amount: {entry!r}")

    # talking_points: no hard digit requirement — qualitative but client-specific
    # points (e.g. ESG alternatives, proposal follow-up) are valid without a number.
    # The system prompt encourages quantification; we don't retry on omissions here.

    # READ checks
    read = out.get("read") or {}
    read_text = read.get("text") or ""
    if read_text:
        # Collect all numbers already present in the non-read sections
        existing_nums = re.findall(r"[\d,]+\.?\d*", " ".join(filter(None, [
            out.get("headline"),
            *[f"{a.get('title','')} {a.get('detail','')}" for a in (out.get("attention") or [])],
            *((out.get("since_last") or [])),
            *((out.get("talking_points") or [])),
        ])))
        # Numeric-value comparison with tolerance — handles normal model rounding
        # (e.g. "87.3" in attention → "87" in read.text).
        # Exact string match was too strict; substring containment was too loose.
        # Tolerance: 1 unit absolute OR 2% relative, whichever is larger.
        # Single-digit numbers (0-9) are skipped — too common to be meaningful anchors.
        existing_vals: list[float] = []
        for n in existing_nums:
            try:
                existing_vals.append(float(n.replace(",", "")))
            except ValueError:
                pass
        for num in re.findall(r"[\d,]+\.?\d*", read_text):
            clean = num.replace(",", "")
            if not clean or (clean.replace(".", "").isdigit() and len(clean.replace(".", "")) <= 1):
                continue  # skip single-digit numbers
            try:
                val = float(clean)
            except ValueError:
                continue
            if not any(abs(val - e) <= max(1.0, abs(e) * 0.02) for e in existing_vals):
                issues.append(
                    f"read.text contains number {num!r} not found in other sections"
                )
                break  # one report per response is enough

        # "will" not preceded/followed by "not" within ~3 words
        for m in re.finditer(r"\bwill\b", read_text, re.IGNORECASE):
            window = read_text[max(0, m.start() - 20): m.end() + 20]
            if "not" not in window.lower():
                issues.append(
                    f"read.text contains bare 'will' (use 'could'/'would' instead): {window!r}"
                )
                break

    # No vague word without a nearby digit
    all_text = " ".join(filter(None, [
        out.get("headline"),
        *[f"{a.get('title','')} {a.get('detail','')}" for a in (out.get("attention") or [])],
        *((out.get("since_last") or [])),
        *((out.get("talking_points") or [])),
    ]))
    for match in _VAGUE_RE.finditer(all_text):
        start, end = match.start(), match.end()
        window = all_text[max(0, start - 40):end + 40]
        if not _DIGIT_RE.search(window):
            issues.append(f"Vague word without nearby number: {match.group()!r} in {window!r}")

    return issues


def _format_saa_deviations(context: dict) -> str:
    """
    Serialize the full saa_target_deviations list from the BriefingContext
    into a readable text block. This data is computed by the analysis layer
    for every client but was previously never sent to the model — only items
    that crossed a priority threshold reached the prompt, leaving large
    allocation drifts invisible on "clean" clients.
    """
    devs = context.get("saa_target_deviations") or []
    if not devs:
        return "No SAA deviation data available."
    lines = []
    for d in devs:
        actual = d.get("actual")
        target = d.get("target")
        dev_pp = d.get("deviation_from_target_pp")
        if actual is None or target is None or dev_pp is None:
            continue
        direction = "above" if dev_pp > 0 else "below"
        lines.append(
            f"- {d.get('category')} ({d.get('dimension')}): "
            f"actual {actual:.1%}, target {target:.1%}, {dev_pp:+.1f} pp {direction} target"
        )
    return "\n".join(lines) if lines else "No SAA deviations to report."


# ── model call ─────────────────────────────────────────────────────────────
def _generate(context: dict, max_attempts: int = 3) -> dict:
    """
    Call the Anthropic model with the /api/briefing prompt shape.
    Returns a dict matching _ModelOutput after Pydantic validation.
    Raises HTTPException(502) if all attempts fail.
    """
    try:
        anthropic_client = _default_client()
    except BriefingGenerationError as e:
        raise HTTPException(status_code=502, detail=str(e))

    fragments = context_to_prose(context)
    user_msg = (
        f"{fragments['client_and_portfolio']}\n\n"
        f"RECENT PERFORMANCE:\n{fragments['performance']}\n\n"
        f"ISSUES AND RISKS:\n{fragments['priorities']}\n\n"
        f"SAA TARGET DEVIATIONS (all dimensions currently out of band — include these even when no "
        f"priority threshold was triggered):\n{_format_saa_deviations(context)}\n\n"
        f"TOP RISK CONTRIBUTORS:\n{fragments['risk_contributors']}\n\n"
        f"CHANGES SINCE LAST INTERACTION:\n{fragments['change_since_last_interaction']}\n\n"
        f"HOUSE VIEW COMPARISON:\n{fragments['house_view']}\n\n"
        f"MARKET NEWS:\n{fragments['news']}\n\n"
        f"WATCH FOR (single-factor approximation):\n{fragments['watch_for']}\n\n"
        f"Respond with the JSON briefing object now."
    )

    last_error = "unknown"
    for attempt in range(max_attempts):
        try:
            response = anthropic_client.chat.completions.create(
                model=BRIEFING_MODEL,
                max_tokens=1200,
                temperature=0,
                messages=[
                    {"role": "system", "content": _SYSTEM},
                    {"role": "user", "content": user_msg},
                ],
                response_format={"type": "json_object"},
            )
        except Exception as e:
            last_error = f"API call failed: {e!r}"
            continue

        raw = _extract_text(response)
        try:
            parsed = _parse_json_response(raw)
            validated = _ModelOutput(**parsed)
            issues = _check_output(validated.model_dump())
            if issues:
                last_error = f"Output quality check failed: {'; '.join(issues)}"
                continue
            return validated.model_dump()
        except (BriefingGenerationError, ValidationError, Exception) as e:
            last_error = f"Parse/validation failed: {e!r}"

    raise HTTPException(status_code=502, detail=f"Briefing generation failed: {last_error}")


# ── /api/briefing ──────────────────────────────────────────────────────────
@app.post("/api/briefing", response_model=BriefingResponse)
def briefing(req: BriefingRequest, fresh: bool = False) -> BriefingResponse:
    cache_key = (req.client_id, req.portfolio_id)
    if not fresh and cache_key in _cache:
        return _cache[cache_key]

    raw_client = _client_by_id.get(req.client_id)
    if raw_client is None:
        raise HTTPException(status_code=404, detail=f"Client '{req.client_id}' not found")

    view = build_client_view(raw_client, _ref)
    bundles = build_client_priorities(view, _ref)

    if not bundles:
        raise HTTPException(status_code=404, detail="No portfolio found for this client")

    # pick portfolio; if portfolio_id provided, prefer it
    if req.portfolio_id:
        bundle = next(
            (b for b in bundles if str(b.get("portfolio_id")) == req.portfolio_id),
            bundles[0],
        )
    else:
        bundle = bundles[0]

    portfolio_id = str(bundle["portfolio_id"])
    portfolio = next(
        (p for p in view["portfolios"] if str(p.get("PortfolioId")) == portfolio_id),
        None,
    )

    # state diff (best-effort; skip on any error)
    try:
        state_result = refresh_client_state(view, bundles, state_dir=STATE_DIR)
        port_state = state_result["portfolios"].get(portfolio_id)
    except Exception:
        port_state = None

    house_view = compare_portfolio_to_house_view(portfolio) if portfolio else []
    context = build_briefing_context(view, bundle, port_state, house_view, [])
    # Stash the full SAA deviations list so _format_saa_deviations() can reach
    # it — build_briefing_context doesn't include this field and it would
    # otherwise be invisible to the model on clients with no priority threshold.
    context["saa_target_deviations"] = bundle.get("saa_target_deviations") or []

    model_out = _generate(context)

    # build client info from data (not generated by model)
    risk_profile = view.get("risk_profile")
    aum = (
        portfolio.get("AssetsUnderManagementInDefaultCurrency")
        if portfolio else view.get("aum")
    )
    assets_str = f"CHF {aum:,.0f}" if aum is not None else "N/A"
    client_type = "Company" if raw_client.get("IsClientACompany") else "Individual"
    profile_name = risk_profile.get("Name", "N/A") if risk_profile else "N/A"
    raw_age = raw_client.get("Age")

    client_info = ClientInfo(
        name=view["display_name"],
        id=req.client_id,
        type=client_type,
        profile=profile_name,
        assets_chf=assets_str,
        age=int(raw_age) if raw_age is not None else None,
    )

    # ── build source references from the actual data that fed the model ──────
    sources: list[SourceRef] = []

    all_priorities = bundle.get("priorities") or []
    violations = [p for p in all_priorities if p.get("type") == "violation"]
    if violations:
        n_err  = sum(1 for v in violations if v.get("severity") == "Error")
        n_warn = sum(1 for v in violations if v.get("severity") == "Warning")
        sources.append(SourceRef(
            section="Suitability violations",
            field="active_violations",
            detail=f"{len(violations)} active — {n_err} Error, {n_warn} Warning",
        ))

    saa_devs = bundle.get("saa_target_deviations") or []
    if saa_devs:
        worst = max(saa_devs, key=lambda d: abs(d["deviation_from_target_pp"]))
        sources.append(SourceRef(
            section="SAA target deviations",
            field="saa_target_deviations",
            detail=(
                f"{len(saa_devs)} dimensions out of band; "
                f"largest: {worst['category']} {worst['deviation_from_target_pp']:+.1f} pp"
            ),
        ))

    rcs = bundle.get("top_risk_contributors") or []
    if rcs:
        top = rcs[0]
        sources.append(SourceRef(
            section="Risk contributors",
            field="risk_attribution",
            detail=(
                f"Top {len(rcs)} positions by contribution volatility; "
                f"largest: {top.get('SecurityName', '?')} "
                f"({top.get('share_of_portfolio_volatility', 0) * 100:.1f}% of portfolio vol)"
            ),
        ))

    perf_history = (portfolio or {}).get("PerformanceHistory") or []
    if perf_history:
        dates = sorted(p["Date"] for p in perf_history if "Date" in p)
        span = f"{dates[0]} to {dates[-1]}" if len(dates) >= 2 else (dates[0] if dates else "")
        sources.append(SourceRef(
            section="Performance history",
            field="PerformanceHistory",
            detail=f"{len(perf_history)} data points ({span})",
        ))

    if house_view:
        as_of = house_view[0].get("as_of", "N/A")
        is_mock = house_view[0].get("is_mock", True)
        sources.append(SourceRef(
            section="House view",
            field="house_view",
            detail=(
                f"{len(house_view)} asset-class stances, as of {as_of}"
                + (" (mock)" if is_mock else "")
            ),
        ))

    notes = view.get("notes") or []
    if notes:
        latest = max((n.get("CreatedByDateUTC", "")[:10] for n in notes), default="")
        sources.append(SourceRef(
            section="Client notes",
            field="ClientNotes",
            detail=f"{len(notes)} note{'s' if len(notes) != 1 else ''}, latest {latest}",
        ))

    tags = [t.get("TagName") for t in (view.get("tags") or []) if t.get("TagName")]
    if tags:
        sources.append(SourceRef(
            section="Client interest tags",
            field="Tags",
            detail=", ".join(tags),
        ))

    watch_for = context.get("watch_for") or {}
    if watch_for:
        factor    = watch_for.get("factor", "")
        shock_pct = watch_for.get("shock_pct")
        chf_impact = watch_for.get("chf_impact")
        detail_parts = [f"factor: {factor}"]
        if shock_pct is not None:
            detail_parts.append(f"shock: {shock_pct:+.0%}")
        if chf_impact is not None:
            detail_parts.append(f"CHF impact: {chf_impact:,.0f}")
        sources.append(SourceRef(
            section="Watch for (shock propagation)",
            field="watch_for",
            detail="; ".join(detail_parts),
        ))

    result = BriefingResponse(client=client_info, sources=sources, **model_out)
    _cache[cache_key] = result
    return result


# ── /api/chat ─────────────────────────────────────────────────────────────

_CHAT_SYSTEM = """\
You are an advisory assistant inside URO Advisor Pro. A wealth advisor is reviewing
a specific client and asking follow-up questions after reading the briefing.
You have access to the client's full portfolio data in the message below.

Rules — follow exactly:
- Answer ONLY from the data provided. Quote specific numbers (%, CHF amounts, dates,
  security names) whenever they are relevant.
- If the information needed to answer is not in the provided data, say explicitly:
  "This information is not available in the data provided."
- Keep answers concise and factual — the advisor needs quick, actionable answers.
- Translate German terms to English in your responses.
- Do not invent positions, rules, proposals, or news not present in the data.
- For rebalancing-effect questions: reason from current allocation vs. SAA targets
  (direction and magnitude only); never project future values or returns.
- Do not repeat the full data section back — just answer the question.
"""

_CHAT_MAX_HISTORY = 10   # turns kept in context; controls cost


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    client_id: str
    portfolio_id: Optional[str] = None
    messages: list[ChatMessage]   # full history including the new user message


class ChatResponse(BaseModel):
    content: str


def _format_all_positions(portfolio: Optional[dict]) -> str:
    """All portfolio positions sorted by risk contribution, with weight and CHF amount."""
    if not portfolio:
        return "No position data available."
    positions = portfolio.get("SecurityPositions") or []
    if not positions:
        return "No positions in this portfolio."

    total_vol = sum(p.get("ContributionVolatility") or 0 for p in positions)
    sorted_pos = sorted(
        positions,
        key=lambda p: p.get("ContributionVolatility") or 0,
        reverse=True,
    )
    from enrichment.market_news import clean_security_name
    lines = []
    for p in sorted_pos:
        name = clean_security_name(p.get("SecurityName") or "Unknown")
        parts = []
        weight = p.get("PortfolioValuePercentage")
        amount = p.get("TotalAmountInPortfolioCurrency")
        vol    = p.get("ContributionVolatility")
        if weight is not None:
            parts.append(f"{weight:.1%} of portfolio")
        if amount is not None:
            parts.append(f"CHF {amount:,.0f}")
        if vol is not None and total_vol > 0:
            parts.append(f"{vol / total_vol:.0%} of portfolio risk")
        lines.append(f"- {name}: {', '.join(parts)}" if parts else f"- {name}")
    return "\n".join(lines)


def _format_proposals(view: dict, portfolio_id: str) -> str:
    """All proposals for this portfolio, most recent first."""
    proposals = view.get("proposals") or []
    port_proposals = [p for p in proposals if str(p.get("PortfolioId")) == portfolio_id]
    if not port_proposals:
        return "No proposals on file for this portfolio."

    port_proposals.sort(key=lambda p: p.get("ProposedDateUTC") or "", reverse=True)
    lines = []
    for p in port_proposals:
        date   = (p.get("ProposedDateUTC") or "")[:10]
        status = p.get("ProposalStatusName") or "Unknown"
        ptype  = p.get("AdvisoryTypeName") or ""
        reason = p.get("Reason") or ""
        notes  = p.get("Notes") or ""
        line = f"- {date} [{status}] {ptype}"
        if reason:
            line += f": {reason}"
        if notes and notes.lower() != "comment":
            line += f" — {notes}"
        lines.append(line)
    return "\n".join(lines)


@app.post("/api/chat", response_model=ChatResponse)
def chat(req: ChatRequest) -> ChatResponse:
    raw_client = _client_by_id.get(req.client_id)
    if raw_client is None:
        raise HTTPException(status_code=404, detail=f"Client '{req.client_id}' not found")

    view    = build_client_view(raw_client, _ref)
    bundles = build_client_priorities(view, _ref)
    if not bundles:
        raise HTTPException(status_code=404, detail="No portfolio found for this client")

    if req.portfolio_id:
        bundle = next(
            (b for b in bundles if str(b.get("portfolio_id")) == req.portfolio_id),
            bundles[0],
        )
    else:
        bundle = bundles[0]

    portfolio_id = str(bundle["portfolio_id"])
    portfolio    = next(
        (p for p in view["portfolios"] if str(p.get("PortfolioId")) == portfolio_id),
        None,
    )

    # Build context — no state refresh here (avoids overwriting the briefing baseline;
    # the advisor already saw "since last interaction" in the briefing itself)
    house_view = compare_portfolio_to_house_view(portfolio) if portfolio else []
    context    = build_briefing_context(view, bundle, None, house_view, [])
    context["saa_target_deviations"] = bundle.get("saa_target_deviations") or []

    fragments = context_to_prose(context)

    data_block = (
        f"{fragments['client_and_portfolio']}\n\n"
        f"CLIENT NOTES / CIRCUMSTANCES:\n{fragments['client_notes']}\n\n"
        f"CLIENT INTERESTS:\n{fragments['client_interests']}\n\n"
        f"RECENT PERFORMANCE:\n{fragments['performance']}\n\n"
        f"ISSUES AND RISKS:\n{fragments['priorities']}\n\n"
        f"SAA TARGET DEVIATIONS:\n{_format_saa_deviations(context)}\n\n"
        f"ALL PORTFOLIO POSITIONS (sorted by risk contribution):\n"
        f"{_format_all_positions(portfolio)}\n\n"
        f"TOP RISK CONTRIBUTORS:\n{fragments['risk_contributors']}\n\n"
        f"HOUSE VIEW COMPARISON:\n{fragments['house_view']}\n\n"
        f"OPEN PROPOSALS:\n{_format_proposals(view, portfolio_id)}\n\n"
        f"MARKET NEWS:\n{fragments['news']}"
    )

    # Trim history and prepend the data block as a system-level context message
    history = req.messages[-_CHAT_MAX_HISTORY:]
    messages = [
        {"role": "system",  "content": _CHAT_SYSTEM},
        {"role": "user",    "content": f"CLIENT DATA:\n\n{data_block}"},
        {"role": "assistant","content": "Understood. I have the full client data. What would you like to know?"},
        *[{"role": m.role, "content": m.content} for m in history],
    ]

    try:
        anthropic_client = _default_client()
    except BriefingGenerationError as e:
        raise HTTPException(status_code=502, detail=str(e))

    try:
        response = anthropic_client.chat.completions.create(
            model=BRIEFING_MODEL,
            max_tokens=400,
            temperature=0.1,
            messages=messages,
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Chat model call failed: {e!r}")

    answer = _extract_text(response).strip()
    if not answer:
        raise HTTPException(status_code=502, detail="Model returned an empty response.")
    return ChatResponse(content=answer)


# ── static demo front end ─────────────────────────────────────────────────
# Mounted AFTER API routes so /api/* is always handled by the router above.
app.mount("/", StaticFiles(directory="demo/static", html=True), name="static")
