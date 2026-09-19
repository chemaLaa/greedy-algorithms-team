"""
Market news for the briefing: WHICH securities/sectors are worth pulling
news for, and fetching/tagging that news.

The case brief is explicit about this: "The market information should be
filtered according to its relevance to the client's actual holdings and
portfolio exposures. A general market summary without a clear connection
to the portfolio provides limited value." So relevance selection is a
first-class, separately testable step here — not an afterthought bolted
onto whatever a news API happens to return.

Budgets (hard caps, not soft targets): at most BUDGET_MAX_SEARCH_SUBJECTS
subjects are searched per portfolio, at most BUDGET_MAX_ARTICLES_PER_SUBJECT
articles are pulled per subject, and at most BUDGET_MAX_RETAINED_ARTICLES
unique articles survive into the briefing — keeping the news section
bounded regardless of how large or newsworthy a portfolio's holdings are.
Subjects are ranked by priority_score (analysis_layer v2's own ranking,
where a subject came from a v2 priority fact) before the cap is applied,
so a hard budget never silently drops the most important subject in favor
of one that happened to be discovered first.

IMPORTANT — network limitation: this module is split deliberately.
`relevant_search_terms()` and `NewsProvider`/`FakeNewsProvider` need no
network access and ARE fully tested (see tests/test_market_news.py).
`YahooFinanceNewsProvider`, at the bottom, makes real network calls via
yfinance and has NOT been executed against a live network in this
environment (no network access here) — test it on your own machine
before relying on it.

VERIFIED ON REAL NETWORK (by Hamza, not in this sandbox): individual
operating companies (e.g. "Novartis AG", "Sandoz Group AG") return real
news reliably. Fund/ETF/index names (e.g. "CSIF (CH) Equity Switzerland
Large Cap Blue", "MSCI World Socially Responsible UCITS ETF") return
NOTHING — 0/6 in manual testing — because they aren't "story" securities
with their own news coverage, unlike an operating company. Since a large
share of this dataset's holdings are funds, `relevant_search_terms()`
below detects a fund position (via IsUnbundlingEnabled, when a
ReferenceIndex is supplied) and searches its largest underlying sector
exposure instead of its own name — both more likely to return real news,
and arguably more relevant to the case's "connection to the portfolio"
requirement than company news about the ETF issuer would be anyway.
"""
from __future__ import annotations

import concurrent.futures
import re
from datetime import datetime, timezone
from typing import Optional, Protocol

# --- budgets ---

BUDGET_MAX_SEARCH_SUBJECTS = 5
BUDGET_MAX_ARTICLES_PER_SUBJECT = 2
BUDGET_MAX_RETAINED_ARTICLES = 6

FRESHNESS_PREFERRED_DAYS = 7
FRESHNESS_FALLBACK_DAYS = 14

# Search subjects are fetched concurrently (small, independent, I/O-bound
# HTTP calls) rather than one at a time. Capped independently of
# BUDGET_MAX_SEARCH_SUBJECTS so a caller that passes a larger custom
# `terms` list directly to fetch_relevant_news_bundle() never spins up an
# unbounded number of threads.
MAX_CONCURRENT_FETCHES = 8

# A look-through industry exposure at or above this absolute share of the
# portfolio is "material" enough to warrant a news subject on its own,
# even with no SAA breach behind it (requirement: a large sector bet the
# portfolio's own SAA happens to have no bound on shouldn't go unsearched
# just because nothing technically breached).
INDUSTRY_MATERIALITY_THRESHOLD = 0.10


def clean_security_name(raw_name: str) -> str:
    """
    Strips Swiss/German banking-system naming conventions down to
    something usable as a news search query. Verified against every one
    of the 504 securities in the real dataset, not just a sample — see
    the "known limitations" note below for what's deliberately NOT
    handled and why.

    Share-type prefixes (simple strip, optionally followed by a
    share-class marker like "-B "):
      "Namen-Aktie Nestle SA"                    -> "Nestle SA"
      "Inhaber-Aktie The Swatch Group AG"        -> "The Swatch Group AG"
      "Na. u. Inh. Ti.-Aktie -B Novo Nordisk A/S" -> "Novo Nordisk A/S"
      "Genussschein Roche Holding AG"            -> "Roche Holding AG"
      "Partizipationsschein Chocoladefabriken
       Lindt & Spruengli AG"                     -> "Chocoladefabriken Lindt & Spruengli AG"

    Fund-unit prefixes ("Anteile", "Shs", "Units", "Accum Shs", "Accum
    Units", "Accum Instit"): the actual fund name is reliably the text
    after the LAST " - " separator, regardless of how messy the
    share-class/currency code prefix is:
      "Anteile -FB- Credit Suisse Index Fd (CH)
       Umbrella - CSIF (CH) Bond Switzerland AAA-AA Blue" -> "CSIF (CH) Bond Switzerland AAA-AA Blue"
      "Shs -A- USD UBS (Irl) ETF PLC - MSCI USA
       Socially Responsible UCITS ETF"                    -> "MSCI USA Socially Responsible UCITS ETF"
    When there's no " - " at all (rare), just the prefix itself is
    stripped: "Shs Global X Data Center REITs..." -> "Global X Data Center REITs..."

    Bond names: leading coupon and trailing maturity-date-and-beyond are
    stripped, leaving the issuer:
      "0.7 % John Deere Capital Corp 2021-01.11.28 Global Series H" -> "John Deere Capital Corp"

    KNOWN LIMITATION, by design: structured products / derivatives
    ("Call-Opt.", "PERLES", "Protection Participation", "Underlying
    Tracker", "Exchange Traded Product", "RC Notes" — about 10 securities
    in the real dataset) and a handful of apparently truncated Name
    values in the source data itself (e.g. bare "12.", "Kap") are NOT
    specially handled and pass through mostly unchanged. These are a
    small, bounded fraction of the dataset (well under 5%) with no clean
    general pattern to exploit. relevant_search_terms() below treats
    these same names as "unresolved" and deliberately skips generating a
    search term for them rather than guessing an issuer from a raw,
    unrecognizable string — see _is_unresolved_security_name().
    """
    name = raw_name.strip()

    for prefix in _SHARE_TYPE_PREFIXES:
        if name.startswith(prefix):
            remainder = name[len(prefix):].strip()
            # A few of these have a share-class marker right after the
            # prefix, e.g. "-B Novo Nordisk A/S" — strip a single
            # "-XXX " token if present.
            remainder = re.sub(r"^-\S+\s+", "", remainder)
            return remainder.strip()

    for prefix in _FUND_UNIT_PREFIXES:
        if name.startswith(prefix):
            if " - " in name:
                return name.rsplit(" - ", 1)[-1].strip()
            return name[len(prefix):].strip()

    bond_match = re.match(r"^[\d.]+\s*%\s*(.+)$", name)
    if bond_match:
        issuer_and_rest = bond_match.group(1)
        issuer = re.sub(r"\s+\d{4}-\d{2}\.\d{2}\.\d{2}.*$", "", issuer_and_rest)
        return issuer.strip()

    if name.endswith(" Aktie"):
        return name[: -len(" Aktie")].strip()

    # Generic fallback: a name with no recognized prefix but that still
    # contains " - " (e.g. "USD iShares IV PLC - iShares MSCI China UCITS
    # ETF") is very likely another fund-unit naming variant this dataset
    # didn't need a dedicated prefix entry for — the same "last segment
    # is the real name" rule applies. A name with no " - " at all falls
    # through unchanged (see the "known limitation" note above).
    if " - " in name:
        return name.rsplit(" - ", 1)[-1].strip()

    return name


# Order doesn't matter within each list — every entry has a distinct
# first word, so at most one can ever match a given name's start.
_SHARE_TYPE_PREFIXES = [
    "Na. u. Inh. Ti.-Aktie",
    "Namen-Aktie",
    "Inhaber-Aktie",
    "Genussschein",
    "Partizipationsschein",
]

_FUND_UNIT_PREFIXES = [
    "Anteile",
    "Accum Instit",
    "Accum Shs",
    "Accum Units",
    "Units",
    "Shs",
]

# Structured-product / derivative markers clean_security_name() is
# documented not to handle (see its docstring's "known limitation").
# Searching news for one of these raw strings, or for a bare truncated
# source-data stub like "12." or "Kap", risks matching an unrelated
# company under a guessed name — so these are excluded from search-term
# generation entirely rather than searched as-is.
_UNRESOLVED_NAME_MARKERS = (
    "Call-Opt.",
    "PERLES",
    "Protection Participation",
    "Underlying Tracker",
    "Exchange Traded Product",
    "RC Notes",
)


def _is_unresolved_security_name(raw_name: Optional[str]) -> bool:
    """
    True for a security name clean_security_name() can't reliably turn
    into a real issuer/company name: a known structured-product marker,
    or a string with no recognizable word at all (e.g. a bare truncated
    stub like "12." or "Kap" seen in the source data). Callers should
    skip generating a search term for these rather than guess.
    """
    if not raw_name or not raw_name.strip():
        return True
    stripped = raw_name.strip()
    if any(marker in stripped for marker in _UNRESOLVED_NAME_MARKERS):
        return True
    if not re.search(r"[A-Za-z]{3,}", stripped):
        return True
    return False


class NewsProvider(Protocol):
    def fetch(self, query: str, max_results: int = 5) -> list[dict]:
        """
        Returns a list of articles, each:
        {"title": str, "publisher": str, "link": str,
         "published_at": <epoch seconds or ISO string>, "summary": str}

        A genuine fetch failure (network error, provider outage, bad
        response) should be raised as an exception, not swallowed into an
        empty list — fetch_relevant_news_bundle() depends on being able
        to tell "the provider found nothing" apart from "the provider
        never got to look".
        """
        ...


def _fund_theme_query(security_id: int, ref) -> Optional[str]:
    """
    For a fund/ETF position, picks a sector-level search theme instead of
    the fund's own name: its single largest underlying Industry exposure
    BY ABSOLUTE WEIGHT (via data_layer.fund_lookthrough.fund_breakdown),
    falling back to the fund's own SAA_AssetClassName (e.g. "Shares") if
    no Industry breakdown is available for it. Returns None if neither is
    available (security not found, or genuinely no breakdown data at all).

    Uses abs() deliberately: FundUnbundlingMappings can carry negative
    weights for short/hedging exposures (see analysis_layer.validation's
    audit_reference_data, which tracks negative_weight_row_count), and a
    plain max() would let a small positive weight beat a much larger
    short position just because it's the wrong sign — silently losing the
    fund's actual largest bet.
    """
    from data_layer.fund_lookthrough import fund_breakdown

    breakdown = fund_breakdown(security_id, "Industry", ref)
    if breakdown:
        return max(breakdown, key=lambda pair: abs(pair[1]))[0]  # largest absolute weight wins

    security = ref.security(security_id)
    if security and security.get("SAA_AssetClassName"):
        return security["SAA_AssetClassName"]

    return None


def _fact_id(portfolio_id, kind: str, suffix) -> Optional[str]:
    if portfolio_id is None or suffix is None:
        return None
    return f"{portfolio_id}:{kind}:{suffix}"


def relevant_search_terms(
    portfolio: dict,
    priorities_bundle: dict,
    ref=None,
    top_n: int = 3,
    max_subjects: int = BUDGET_MAX_SEARCH_SUBJECTS,
) -> list[dict]:
    """
    Picks WHAT to search news for, grounded in the portfolio's own
    analysis output rather than anything generic. Combines:
      - the portfolio's top risk contributors (individual securities,
        from analysis_layer.performance.risk_contributor_analysis /
        top_risk_contributors) — but ONLY when analysis_layer v2's own
        risk_attribution quality check says that data is usable. If
        priorities_bundle["risk_attribution"]["status"] is "invalid" or
        "unavailable", ContributionVolatility didn't reconcile to
        portfolio volatility (or wasn't populated at all) — generating a
        news search off numbers analysis_layer itself has already
        flagged as unusable would launder a data-quality problem into an
        apparently-confident news subject. A bundle with no
        "risk_attribution" key at all (older/simplified bundles, e.g. in
        tests) is treated as usable, matching pre-v2 behavior.
      - concentration and SAA-breach flags already surfaced in the
        priority list (from analysis_layer.prioritize.build_client_priorities),
        reusing v2's own priority_score for ranking rather than
        recomputing one
      - material look-through industry exposure (from
        priorities_bundle["concentrations"]["dimensions"]["Industry"]),
        even when nothing there breached an SAA bound — a large sector
        bet the portfolio's SAA happens to have no bound on is still
        worth a news subject

    `ref` (a data_layer.ReferenceIndex) is optional but recommended: when
    supplied, a top risk contributor that's a FUND gets a sector-theme
    query instead of its own name (see module docstring for why — fund
    names verified to return no news on the real API). Without `ref`,
    every contributor falls back to its cleaned security name regardless
    of type, matching the older behavior.

    A security name clean_security_name() can't reliably resolve to an
    issuer (see _is_unresolved_security_name()) never becomes a search
    term — never guessing an issuer beats searching a raw, unrecognizable
    string and risking an unrelated company's news.

    Returns [{"type": "security"|"sector", "query": str, "reason": str,
    "priority_score": float, "fact_id": str|None}], de-duplicated by
    query (keeping the highest-priority copy), ranked by priority_score
    descending, and capped at `max_subjects` (BUDGET_MAX_SEARCH_SUBJECTS
    by default) — the hard subject budget is applied here, before any
    external call is made.
    """
    portfolio_id = priorities_bundle.get("portfolio_id")
    terms: list[dict] = []

    risk_attribution = priorities_bundle.get("risk_attribution")
    risk_status = risk_attribution.get("status") if risk_attribution is not None else "ok"
    contributors = [] if risk_status in ("invalid", "unavailable") else priorities_bundle.get("top_risk_contributors", [])

    for contributor in contributors[:top_n]:
        name = contributor.get("SecurityName")
        if not name:
            continue

        share = contributor.get("share_of_portfolio_volatility")
        share_str = f" ({share:.0%} of portfolio volatility)" if share is not None else ""
        priority_score = min(100.0, 60.0 + 100.0 * (share or 0.0))

        security_id = contributor.get("SecurityId")
        security = ref.security(security_id) if (ref is not None and security_id is not None) else None

        if security and security.get("IsUnbundlingEnabled"):
            theme = _fund_theme_query(security_id, ref)
            if theme:
                terms.append(
                    {
                        "type": "sector",
                        "query": theme,
                        "reason": (
                            f"largest look-through sector exposure within {clean_security_name(name)}, "
                            f"a top portfolio risk contributor{share_str}"
                        ),
                        "priority_score": priority_score,
                        "fact_id": _fact_id(portfolio_id, "risk_contributor", security_id),
                    }
                )
                continue  # skip the fund-name query — verified low value on real API

        if _is_unresolved_security_name(name):
            continue

        terms.append(
            {
                "type": "security",
                "query": clean_security_name(name),
                "reason": f"top portfolio risk contributor{share_str}",
                "priority_score": priority_score,
                "fact_id": _fact_id(portfolio_id, "risk_contributor", security_id),
            }
        )

    for item in priorities_bundle.get("priorities", []):
        if item["type"] == "single_position_concentration":
            name = item.get("security_name")
            if _is_unresolved_security_name(name):
                continue
            terms.append(
                {
                    "type": "security",
                    "query": clean_security_name(name),
                    "reason": f"concentrated position ({item['weight']:.0%} of portfolio)",
                    "priority_score": item.get("priority_score", 55.0),
                    "fact_id": item.get("fact_id"),
                }
            )
        elif item["type"] == "saa_breach":
            direction = "below" if item["breach"] == "min" else "above"
            terms.append(
                {
                    "type": "sector",
                    "query": item["category"],
                    "reason": f"{item['dimension']} exposure {direction} target range",
                    "priority_score": item.get("priority_score", 78.0),
                    "fact_id": item.get("fact_id"),
                }
            )

    existing_sector_queries = {t["query"] for t in terms if t["type"] == "sector"}
    industry_rows = ((priorities_bundle.get("concentrations") or {}).get("dimensions") or {}).get("Industry") or []
    for row in industry_rows:
        category = row.get("category")
        if category is None or category in existing_sector_queries:
            continue
        abs_weight = row.get("absolute_weight")
        if abs_weight is None:
            abs_weight = abs(row.get("weight") or 0.0)
        if abs_weight < INDUSTRY_MATERIALITY_THRESHOLD:
            continue
        terms.append(
            {
                "type": "sector",
                "query": category,
                "reason": f"material look-through industry exposure ({abs_weight:.0%} of portfolio, no SAA breach)",
                "priority_score": min(65.0, 30.0 + 100.0 * abs_weight),
                "fact_id": None,
            }
        )
        existing_sector_queries.add(category)

    terms.sort(key=lambda t: -(t.get("priority_score") or 0.0))

    seen = set()
    deduped = []
    for term in terms:
        if term["query"] not in seen:
            seen.add(term["query"])
            deduped.append(term)

    return deduped[:max_subjects]


def _parse_published_at(value) -> Optional[datetime]:
    """Accepts epoch seconds (int/float) or an ISO 8601 string; None if unparseable."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(value, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    if isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    return None


def _article_key(article: dict) -> tuple:
    link = article.get("link")
    if link:
        return ("link", link)
    return ("title_publisher", article.get("title"), article.get("publisher"))


def _merge_duplicate_articles(articles: list[dict]) -> list[dict]:
    """
    Merges articles that matched more than one search query into a single
    entry, retaining every distinct match reason, match type, matched
    query, and connected fact_id — a plain dedupe-by-link would silently
    drop the provenance of whichever copy lost, which is exactly the
    information the synthesis layer needs to explain WHY an article is
    relevant.
    """
    merged: dict[tuple, dict] = {}
    order: list[tuple] = []

    for article in articles:
        key = _article_key(article)
        if key not in merged:
            base = {k: v for k, v in article.items() if k not in ("matched_query", "match_reason", "match_type", "fact_id")}
            merged[key] = {**base, "matched_queries": [], "match_reasons": [], "match_types": [], "fact_ids": []}
            order.append(key)

        entry = merged[key]
        query = article.get("matched_query")
        if query is not None and query not in entry["matched_queries"]:
            entry["matched_queries"].append(query)
        reason = article.get("match_reason")
        if reason is not None and reason not in entry["match_reasons"]:
            entry["match_reasons"].append(reason)
        match_type = article.get("match_type")
        if match_type is not None and match_type not in entry["match_types"]:
            entry["match_types"].append(match_type)
        fact_id = article.get("fact_id")
        if fact_id is not None and fact_id not in entry["fact_ids"]:
            entry["fact_ids"].append(fact_id)

    return [merged[key] for key in order]


def fetch_relevant_news_bundle(
    terms: list[dict],
    provider: "NewsProvider",
    max_per_term: int = BUDGET_MAX_ARTICLES_PER_SUBJECT,
    max_total: int = BUDGET_MAX_RETAINED_ARTICLES,
    now: Optional[datetime] = None,
    max_workers: int = MAX_CONCURRENT_FETCHES,
) -> dict:
    """
    Fetches news for each search term via the given provider CONCURRENTLY
    (a ThreadPoolExecutor — these are small, independent, I/O-bound HTTP
    calls, not CPU work, so threads are the right tool and the GIL isn't a
    bottleneck here), applies the freshness window, merges cross-query
    duplicates, enforces the retained-article budget, and reports an
    explicit status:

      "ok"            — at least one article retained; every subject that
                         was searched fetched successfully.
      "partial"       — at least one article retained, but at least one
                         subject's fetch raised an exception. Usable, but
                         degraded — see `reasons`.
      "no_news_found" — every subject fetched successfully (no exceptions
                         at all) and genuinely returned nothing usable —
                         either the provider found nothing, or everything
                         it found fell outside the 14-day fallback window.
                         A real "quiet market" result.
      "fetch_failed"  — zero articles retained AND at least one subject's
                         fetch raised an exception. This is deliberately
                         a different status from "no_news_found": the
                         caller must not narrate "no relevant market news
                         was found" when the truth is the search itself
                         didn't work.

    One subject's fetch raising never aborts the others — each subject's
    result (success or exception) is collected independently, exactly as
    when fetching sequentially.

    Results are reassembled in the ORIGINAL `terms` order before merging,
    not completion order — concurrency changes how fast this runs, never
    which article wins a duplicate-merge or which articles survive the
    `max_total` cut, so behavior is otherwise identical to a sequential
    fetch.

    `reasons` (a list of strings, same pattern as analysis_layer.validation)
    always explains a non-"ok" status, and `term_results` gives a per-term
    breakdown for debugging, in the same order as `terms`. `now` is
    injectable for deterministic tests; defaults to the real current time.
    """
    now = now or datetime.now(timezone.utc)

    if not terms:
        return {
            "status": "no_news_found",
            "reasons": ["no_search_terms_generated"],
            "articles": [],
            "term_results": [],
            "freshness_window_used": None,
        }

    term_results: list[Optional[dict]] = [None] * len(terms)
    per_term_articles: list[list[dict]] = [[] for _ in terms]
    any_success = False
    any_error = False

    with concurrent.futures.ThreadPoolExecutor(max_workers=min(len(terms), max_workers)) as executor:
        future_to_index = {
            executor.submit(provider.fetch, term["query"], max_results=max_per_term): i
            for i, term in enumerate(terms)
        }
        for future in concurrent.futures.as_completed(future_to_index):
            i = future_to_index[future]
            term = terms[i]
            try:
                fetched = future.result()
            except Exception as e:  # provider/network failure — never silently swallowed
                any_error = True
                term_results[i] = {"query": term["query"], "status": "error", "error": f"{type(e).__name__}: {e}"}
                continue

            any_success = True
            fetched = fetched[:max_per_term]
            term_results[i] = {"query": term["query"], "status": "ok", "article_count": len(fetched)}
            per_term_articles[i] = [
                {
                    **article,
                    "matched_query": term["query"],
                    "match_reason": term["reason"],
                    "match_type": term["type"],
                    "fact_id": term.get("fact_id"),
                }
                for article in fetched
            ]

    raw_articles: list[dict] = [article for bucket in per_term_articles for article in bucket]

    def _within(article: dict, days: int) -> bool:
        published = _parse_published_at(article.get("published_at"))
        if published is None:
            # Unknown publish date is never assumed fresh — never fabricate.
            return False
        return (now - published).total_seconds() <= days * 86400

    reasons: list[str] = []
    preferred = [a for a in raw_articles if _within(a, FRESHNESS_PREFERRED_DAYS)]
    if preferred:
        candidates = preferred
        freshness_window_used = "preferred_7d"
    else:
        fallback = [a for a in raw_articles if _within(a, FRESHNESS_FALLBACK_DAYS)]
        if fallback:
            candidates = fallback
            freshness_window_used = "fallback_14d"
            reasons.append("no_articles_within_preferred_7d_window")
        else:
            candidates = []
            freshness_window_used = "none"
            if raw_articles:
                reasons.append("all_articles_older_than_14d_or_undated")

    merged = _merge_duplicate_articles(candidates)[:max_total]

    if merged:
        status = "partial" if any_error else "ok"
        if any_error:
            reasons.append("some_search_subjects_failed")
    elif any_error:
        status = "fetch_failed"
        reasons.append(
            "all_search_subjects_failed"
            if not any_success
            else "some_search_subjects_failed_and_remaining_results_were_empty_or_stale"
        )
    else:
        status = "no_news_found"
        if not raw_articles:
            reasons.append("no_articles_returned_by_provider")

    return {
        "status": status,
        "reasons": reasons,
        "articles": merged,
        "term_results": term_results,
        "freshness_window_used": freshness_window_used,
    }


def fetch_relevant_news(
    terms: list[dict],
    provider: "NewsProvider",
    max_per_term: int = BUDGET_MAX_ARTICLES_PER_SUBJECT,
    now: Optional[datetime] = None,
) -> list[dict]:
    """
    Backward-compatible list-only wrapper around fetch_relevant_news_bundle()
    for callers that only need the articles and don't care about the
    fetch-failure-vs-no-news distinction.
    """
    return fetch_relevant_news_bundle(terms, provider, max_per_term=max_per_term, now=now)["articles"]


class FakeNewsProvider:
    """
    Deterministic fake provider for tests: returns canned articles keyed
    by query, so relevance-selection and filtering logic above can be
    tested with zero network access. Not meant for real use.
    """

    def __init__(self, canned: dict[str, list[dict]] = None):
        self.canned = canned or {}

    def fetch(self, query: str, max_results: int = 5) -> list[dict]:
        return self.canned.get(query, [])[:max_results]


class FailingNewsProvider:
    """
    Deterministic provider that always raises, for testing
    fetch_relevant_news_bundle()'s failure-vs-no-news distinction without
    a real network dependency.
    """

    def __init__(self, error: Exception = None):
        self.error = error or ConnectionError("simulated provider failure")

    def fetch(self, query: str, max_results: int = 5) -> list[dict]:
        raise self.error


class YahooFinanceNewsProvider:
    """
    Best-effort real news provider using the `yfinance` package.

    NOT TESTED AGAINST A LIVE NETWORK in this environment — this sandbox
    has no network access, so this class is written against yfinance's
    documented API but has never actually been run. Before wiring it into
    synthesis, verify on your own machine:
        pip install yfinance
        python3 -c "from enrichment.market_news import YahooFinanceNewsProvider as Y; print(Y().fetch('Nestle'))"

    Known risk worth checking early: this dataset's securities carry
    ISIN/Valor, not a Yahoo-style ticker (e.g. "NESN.SW"). `fetch()` below
    passes the security's plain NAME to yfinance.Search(), which attempts
    to resolve free-text company names to a ticker before pulling news.
    That resolution is the single most likely point of failure for
    Swiss/European names specifically — if it's unreliable in practice,
    the fix is either a small manual ISIN->ticker lookup table for the
    securities that actually show up as top risk contributors across the
    47 clients (a bounded, checkable list), or falling back to a plain
    web search instead of yfinance's ticker-keyed news endpoint.

    Deliberately does NOT catch its own exceptions: a network/provider
    failure must propagate up to fetch_relevant_news_bundle(), which is
    what turns it into an explicit "fetch_failed" status instead of a
    silently-empty result indistinguishable from "no news found".
    """

    def fetch(self, query: str, max_results: int = 5) -> list[dict]:
        import yfinance as yf

        search = yf.Search(query, news_count=max_results)
        raw_articles = search.news or []

        return [
            {
                "title": a.get("title"),
                "publisher": a.get("publisher"),
                "link": a.get("link"),
                "published_at": a.get("providerPublishTime"),
                "summary": a.get("summary", ""),
            }
            for a in raw_articles[:max_results]
        ]
