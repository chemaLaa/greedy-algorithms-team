"""
Tests for dual-source fetch in fetch_relevant_news_bundle():
  - dedup across two providers
  - source_count accuracy
  - corroboration list logic

Uses FakeNewsProvider with different provider_name attributes — zero network
access required.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from datetime import datetime, timezone

from enrichment.market_news import FakeNewsProvider, fetch_relevant_news_bundle

# A fixed "now" so freshness tests are stable.
_NOW = datetime(2026, 9, 19, 12, 0, 0, tzinfo=timezone.utc)
_RECENT = "2026-09-18T10:00:00+00:00"


def _make_provider(name: str, canned: dict) -> FakeNewsProvider:
    """Build a FakeNewsProvider with a custom provider_name."""
    p = FakeNewsProvider(canned)
    p.provider_name = name
    return p


def _terms(queries: list[str]) -> list[dict]:
    return [
        {
            "type": "sector",
            "query": q,
            "reason": f"test reason for {q}",
            "priority_score": 80.0,
            "fact_id": None,
        }
        for q in queries
    ]


# ---------------------------------------------------------------------------
# Dedup: same article (same link) from both providers → appears once,
# and its `providers` list has 2 entries.
# ---------------------------------------------------------------------------

def test_dedup_same_link_across_two_providers_yields_one_article():
    article = {
        "title": "Tech stocks surge",
        "publisher": "Reuters",
        "link": "http://example.com/tech-surge",
        "published_at": _RECENT,
        "summary": "",
    }
    provider_a = _make_provider("ProviderA", {"Technology": [article]})
    provider_b = _make_provider("ProviderB", {"Technology": [article]})

    bundle = fetch_relevant_news_bundle(
        _terms(["Technology"]),
        providers=[provider_a, provider_b],
        now=_NOW,
    )

    assert bundle["status"] == "ok"
    assert len(bundle["articles"]) == 1
    found = bundle["articles"][0]
    assert set(found["providers"]) == {"ProviderA", "ProviderB"}


def test_dedup_same_title_publisher_no_link_across_two_providers():
    article_no_link = {
        "title": "Tech stocks surge",
        "publisher": "Reuters",
        "link": "",
        "published_at": _RECENT,
        "summary": "",
    }
    provider_a = _make_provider("ProviderA", {"Technology": [article_no_link]})
    provider_b = _make_provider("ProviderB", {"Technology": [article_no_link]})

    bundle = fetch_relevant_news_bundle(
        _terms(["Technology"]),
        providers=[provider_a, provider_b],
        now=_NOW,
    )

    assert len(bundle["articles"]) == 1
    found = bundle["articles"][0]
    assert set(found["providers"]) == {"ProviderA", "ProviderB"}


# ---------------------------------------------------------------------------
# source_count accuracy
# ---------------------------------------------------------------------------

def test_source_count_two_when_both_providers_return_articles():
    article = {
        "title": "Health care outlook",
        "publisher": "Bloomberg",
        "link": "http://example.com/hc",
        "published_at": _RECENT,
        "summary": "",
    }
    provider_a = _make_provider("ProviderA", {"Health Care": [article]})
    provider_b = _make_provider("ProviderB", {"Health Care": [article]})

    bundle = fetch_relevant_news_bundle(
        _terms(["Health Care"]),
        providers=[provider_a, provider_b],
        now=_NOW,
    )

    tr = bundle["term_results"][0]
    assert tr["source_count"] == 2
    assert "ProviderA" in tr["providers"]
    assert "ProviderB" in tr["providers"]


def test_source_count_one_when_only_one_provider_returns_articles():
    article = {
        "title": "Energy report",
        "publisher": "FT",
        "link": "http://example.com/energy",
        "published_at": _RECENT,
        "summary": "",
    }
    provider_a = _make_provider("ProviderA", {"Energy": [article]})
    provider_b = _make_provider("ProviderB", {})  # returns nothing

    bundle = fetch_relevant_news_bundle(
        _terms(["Energy"]),
        providers=[provider_a, provider_b],
        now=_NOW,
    )

    tr = bundle["term_results"][0]
    assert tr["source_count"] == 1
    assert tr["providers"] == ["ProviderA"]


# ---------------------------------------------------------------------------
# Single-source subject → NOT in corroboration
# ---------------------------------------------------------------------------

def test_single_source_subject_not_in_corroboration():
    article = {
        "title": "Energy report",
        "publisher": "FT",
        "link": "http://example.com/energy",
        "published_at": _RECENT,
        "summary": "",
    }
    provider_a = _make_provider("ProviderA", {"Energy": [article]})
    provider_b = _make_provider("ProviderB", {})  # returns nothing for Energy

    bundle = fetch_relevant_news_bundle(
        _terms(["Energy"]),
        providers=[provider_a, provider_b],
        now=_NOW,
    )

    assert bundle["corroboration"] == []


# ---------------------------------------------------------------------------
# Corroboration present when both providers find same subject
# ---------------------------------------------------------------------------

def test_corroboration_present_when_both_providers_find_subject():
    article_a = {
        "title": "Tech outlook A",
        "publisher": "Reuters",
        "link": "http://example.com/tech-a",
        "published_at": _RECENT,
        "summary": "",
    }
    article_b = {
        "title": "Tech outlook B",
        "publisher": "Bloomberg",
        "link": "http://example.com/tech-b",
        "published_at": _RECENT,
        "summary": "",
    }
    provider_a = _make_provider("ProviderA", {"Technology": [article_a]})
    provider_b = _make_provider("ProviderB", {"Technology": [article_b]})

    bundle = fetch_relevant_news_bundle(
        _terms(["Technology"]),
        providers=[provider_a, provider_b],
        now=_NOW,
    )

    assert len(bundle["corroboration"]) == 1
    corr = bundle["corroboration"][0]
    assert corr["subject"] == "Technology"
    assert corr["source_count"] == 2
    assert "ProviderA" in corr["providers"]
    assert "ProviderB" in corr["providers"]


def test_corroboration_empty_when_no_subjects_have_two_sources():
    article = {
        "title": "Tech story",
        "publisher": "Reuters",
        "link": "http://example.com/tech",
        "published_at": _RECENT,
        "summary": "",
    }
    provider_a = _make_provider("ProviderA", {"Technology": [article]})
    provider_b = _make_provider("ProviderB", {})

    bundle = fetch_relevant_news_bundle(
        _terms(["Technology"]),
        providers=[provider_a, provider_b],
        now=_NOW,
    )

    assert bundle["corroboration"] == []


# ---------------------------------------------------------------------------
# Mixed: one subject from both, one from only one — selective corroboration
# ---------------------------------------------------------------------------

def test_corroboration_selective_when_mixed_coverage():
    article_tech_a = {
        "title": "Tech A",
        "publisher": "Reuters",
        "link": "http://example.com/ta",
        "published_at": _RECENT,
        "summary": "",
    }
    article_tech_b = {
        "title": "Tech B",
        "publisher": "Bloomberg",
        "link": "http://example.com/tb",
        "published_at": _RECENT,
        "summary": "",
    }
    article_energy = {
        "title": "Energy news",
        "publisher": "FT",
        "link": "http://example.com/e",
        "published_at": _RECENT,
        "summary": "",
    }

    provider_a = _make_provider("ProviderA", {"Technology": [article_tech_a], "Energy": [article_energy]})
    provider_b = _make_provider("ProviderB", {"Technology": [article_tech_b]})  # no Energy

    bundle = fetch_relevant_news_bundle(
        _terms(["Technology", "Energy"]),
        providers=[provider_a, provider_b],
        now=_NOW,
    )

    corroboration_subjects = {c["subject"] for c in bundle["corroboration"]}
    assert "Technology" in corroboration_subjects
    assert "Energy" not in corroboration_subjects


# ---------------------------------------------------------------------------
# Backward-compatible single-provider path still works
# ---------------------------------------------------------------------------

def test_single_provider_backward_compat():
    article = {
        "title": "Single provider article",
        "publisher": "Reuters",
        "link": "http://example.com/sp",
        "published_at": _RECENT,
        "summary": "",
    }
    provider = FakeNewsProvider({"Technology": [article]})

    bundle = fetch_relevant_news_bundle(
        _terms(["Technology"]),
        provider=provider,
        now=_NOW,
    )

    assert bundle["status"] == "ok"
    assert len(bundle["articles"]) == 1
    # Single provider → source_count = 1
    assert bundle["term_results"][0]["source_count"] == 1
    # Corroboration empty
    assert bundle["corroboration"] == []
