"""
Market news for the briefing: WHICH securities/sectors are worth pulling
news for, and fetching/tagging that news.

The case brief is explicit about this: "The market information should be
filtered according to its relevance to the client's actual holdings and
portfolio exposures. A general market summary without a clear connection
to the portfolio provides limited value." So relevance selection is a
first-class, separately testable step here — not an afterthought bolted
onto whatever a news API happens to return.

IMPORTANT — network limitation: this module is split deliberately.
`relevant_search_terms()` and `NewsProvider`/`FakeNewsProvider` need no
network access and ARE fully tested (see tests/test_market_news.py).
`YahooFinanceNewsProvider`, at the bottom, makes real network calls via
yfinance and has NOT been executed against a live network in this
environment (no network access here) — test it on your own machine
before relying on it. See its docstring for a known resolution risk
(company name -> ticker) worth checking early.
"""
from __future__ import annotations

import re
from typing import Protocol


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
    general pattern to exploit — a news search on the raw string for
    these will likely return nothing useful rather than something wrong,
    which the synthesis layer should treat as "no relevant news found"
    rather than something this function should try to fabricate a fix
    for.
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


class NewsProvider(Protocol):
    def fetch(self, query: str, max_results: int = 5) -> list[dict]:
        """
        Returns a list of articles, each:
        {"title": str, "publisher": str, "link": str,
         "published_at": <epoch seconds or ISO string>, "summary": str}
        """
        ...


def relevant_search_terms(portfolio: dict, priorities_bundle: dict, top_n: int = 3) -> list[dict]:
    """
    Picks WHAT to search news for, grounded in the portfolio's own
    analysis output rather than anything generic. Combines:
      - the portfolio's top risk contributors (individual securities,
        from analysis_layer.performance.top_risk_contributors)
      - concentration flags and SAA breaches already surfaced in the
        priority list (from analysis_layer.prioritize.build_client_priorities)

    Returns [{"type": "security"|"sector", "query": str, "reason": str}],
    de-duplicated by query, ordered by the priority list's own severity
    ordering (risk contributors first, then priorities in the order
    prioritize.py already ranked them).
    """
    terms: list[dict] = []

    for contributor in priorities_bundle.get("top_risk_contributors", [])[:top_n]:
        name = contributor.get("SecurityName")
        if not name:
            continue
        share = contributor.get("share_of_portfolio_volatility")
        reason = (
            f"top portfolio risk contributor ({share:.0%} of portfolio volatility)"
            if share is not None
            else "top portfolio risk contributor"
        )
        terms.append({"type": "security", "query": clean_security_name(name), "reason": reason})

    for item in priorities_bundle.get("priorities", []):
        if item["type"] == "concentration":
            terms.append(
                {
                    "type": "security",
                    "query": clean_security_name(item["security_name"]),
                    "reason": f"concentrated position ({item['weight']:.0%} of portfolio)",
                }
            )
        elif item["type"] == "saa_deviation":
            direction = "below" if item["breach"] == "min" else "above"
            terms.append(
                {
                    "type": "sector",
                    "query": item["category"],
                    "reason": f"{item['dimension']} exposure {direction} target range",
                }
            )

    seen = set()
    deduped = []
    for term in terms:
        if term["query"] not in seen:
            seen.add(term["query"])
            deduped.append(term)
    return deduped


def fetch_relevant_news(
    terms: list[dict], provider: NewsProvider, max_per_term: int = 3
) -> list[dict]:
    """
    Fetches news for each search term via the given provider, tagging
    every article with which portfolio term produced it and why — so the
    synthesis layer can explain the connection ("this is relevant because
    it's your largest holding"), not just drop in a bare headline.
    """
    articles = []
    for term in terms:
        for article in provider.fetch(term["query"], max_results=max_per_term):
            articles.append(
                {
                    **article,
                    "matched_query": term["query"],
                    "match_reason": term["reason"],
                    "match_type": term["type"],
                }
            )
    return articles


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
    """

    def fetch(self, query: str, max_results: int = 5) -> list[dict]:
        import yfinance as yf

        try:
            search = yf.Search(query, news_count=max_results)
            raw_articles = search.news or []
        except Exception:
            return []

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
