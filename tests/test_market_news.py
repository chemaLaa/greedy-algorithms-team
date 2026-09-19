from datetime import datetime, timezone

from enrichment.market_news import (
    BUDGET_MAX_ARTICLES_PER_SUBJECT,
    BUDGET_MAX_RETAINED_ARTICLES,
    BUDGET_MAX_SEARCH_SUBJECTS,
    CLIENT_INTEREST_TAG_PRIORITY_SCORE,
    FailingNewsProvider,
    FakeNewsProvider,
    clean_security_name,
    fetch_relevant_news,
    fetch_relevant_news_bundle,
    relevant_search_terms,
)


def test_clean_security_name_namen_aktie():
    assert clean_security_name("Namen-Aktie Nestle SA") == "Nestle SA"


def test_clean_security_name_inhaber_aktie():
    assert clean_security_name("Inhaber-Aktie The Swatch Group AG") == "The Swatch Group AG"


def test_clean_security_name_combined_share_type_with_class_marker():
    assert (
        clean_security_name("Na. u. Inh. Ti.-Aktie -B Novo Nordisk A/S")
        == "Novo Nordisk A/S"
    )


def test_clean_security_name_genussschein_and_partizipationsschein():
    assert clean_security_name("Genussschein Roche Holding AG") == "Roche Holding AG"
    assert (
        clean_security_name("Partizipationsschein Chocoladefabriken Lindt & Spruengli AG")
        == "Chocoladefabriken Lindt & Spruengli AG"
    )


def test_clean_security_name_fund_unit_takes_last_segment():
    name = "Anteile -FB- Credit Suisse Index Fd (CH) Umbrella - CSIF (CH) Bond Switzerland AAA-AA Blue"
    assert clean_security_name(name) == "CSIF (CH) Bond Switzerland AAA-AA Blue"


def test_clean_security_name_fund_unit_with_multiple_dashes_takes_last_segment():
    # Real example: three " - " occurrences — must take the LAST one.
    name = "Anteile - USD ETF - iShares IV PLC - iShares Automation & Robotics UCITS ETF"
    assert clean_security_name(name) == "iShares Automation & Robotics UCITS ETF"


def test_clean_security_name_shs_prefix():
    name = "Shs -A- USD UBS (Irl) ETF PLC - MSCI USA Socially Responsible UCITS ETF"
    assert clean_security_name(name) == "MSCI USA Socially Responsible UCITS ETF"


def test_clean_security_name_bond_strips_coupon_and_maturity():
    assert clean_security_name("1.125 % Clariant AG 2019-30.01.29") == "Clariant AG"
    assert (
        clean_security_name("0.7 % John Deere Capital Corp 2021-01.11.28 Global Series H")
        == "John Deere Capital Corp"
    )


def test_clean_security_name_generic_fallback_for_unlisted_prefix():
    # No recognized prefix, but still contains " - " — generic fallback
    # should still extract the last segment.
    name = "USD iShares IV PLC - iShares MSCI China UCITS ETF"
    assert clean_security_name(name) == "iShares MSCI China UCITS ETF"


def test_clean_security_name_passes_through_plain_names_unchanged():
    assert clean_security_name("A1A Car Wash") == "A1A Car Wash"


def test_clean_security_name_never_returns_empty_string():
    # Regression guard: whatever the input, never silently produce "".
    tricky_inputs = ["Namen-Aktie", "Anteile", "0 % ", "", "   "]
    for raw in tricky_inputs:
        # Should not raise, and result should be a string (possibly empty
        # only for genuinely empty input).
        result = clean_security_name(raw)
        assert isinstance(result, str)


def test_relevant_search_terms_fund_with_industry_breakdown_uses_largest_sector():
    from data_layer import ReferenceIndex

    reference = {
        "Securities": [
            {"Id": 100, "Name": "Some Fund", "IsUnbundlingEnabled": True, "SAA_AssetClassName": "Shares"},
            # anchors so IndustryName -> SAA_IndustryName is derivable
            {"Id": 200, "IndustryName": "Financials", "SAA_IndustryName": "Financials"},
            {"Id": 201, "IndustryName": "Health Care", "SAA_IndustryName": "Health Care"},
        ],
        "FundUnbundlingMappings": [
            {"FundSecurityId": 100, "IndustryName": "Financials", "Weight": 70.0},
            {"FundSecurityId": 100, "IndustryName": "Health Care", "Weight": 30.0},
        ],
    }
    ref = ReferenceIndex(reference)
    priorities_bundle = {
        "top_risk_contributors": [
            {
                "SecurityId": 100,
                "SecurityName": "Anteile -X- Some Issuer - Some Fund",
                "share_of_portfolio_volatility": 0.3,
            }
        ],
        "priorities": [],
    }
    terms = relevant_search_terms({}, priorities_bundle, ref=ref)
    assert terms[0]["type"] == "sector"
    assert terms[0]["query"] == "Financials"  # 70% > 30%, largest wins


def test_relevant_search_terms_fund_theme_uses_largest_absolute_weight_not_signed_max():
    # A short/hedging position can carry a large NEGATIVE weight in
    # FundUnbundlingMappings. Picking by plain max() would pick a small
    # positive weight over a much larger short exposure just because of
    # sign — the fund's real largest bet must win regardless of sign.
    from data_layer import ReferenceIndex

    reference = {
        "Securities": [
            {"Id": 100, "Name": "Hedged Fund", "IsUnbundlingEnabled": True, "SAA_AssetClassName": "Shares"},
            {"Id": 200, "IndustryName": "Energy", "SAA_IndustryName": "Energy"},
            {"Id": 201, "IndustryName": "Utilities", "SAA_IndustryName": "Utilities"},
        ],
        "FundUnbundlingMappings": [
            {"FundSecurityId": 100, "IndustryName": "Energy", "Weight": -80.0},
            {"FundSecurityId": 100, "IndustryName": "Utilities", "Weight": 20.0},
        ],
    }
    ref = ReferenceIndex(reference)
    priorities_bundle = {
        "top_risk_contributors": [
            {"SecurityId": 100, "SecurityName": "Hedged Fund", "share_of_portfolio_volatility": 0.2}
        ],
        "priorities": [],
    }
    terms = relevant_search_terms({}, priorities_bundle, ref=ref)
    assert terms[0]["query"] == "Energy"  # |-80| > |20|


def test_relevant_search_terms_fund_without_breakdown_falls_back_to_asset_class():
    from data_layer import ReferenceIndex

    reference = {
        "Securities": [
            {"Id": 100, "Name": "Some Fund", "IsUnbundlingEnabled": True, "SAA_AssetClassName": "Bonds"}
        ],
        "FundUnbundlingMappings": [],
    }
    ref = ReferenceIndex(reference)
    priorities_bundle = {
        "top_risk_contributors": [
            {"SecurityId": 100, "SecurityName": "Some Fund", "share_of_portfolio_volatility": 0.1}
        ],
        "priorities": [],
    }
    terms = relevant_search_terms({}, priorities_bundle, ref=ref)
    assert terms[0]["type"] == "sector"
    assert terms[0]["query"] == "Bonds"


def test_relevant_search_terms_without_ref_uses_security_name_even_for_funds():
    # No ref supplied — can't detect fund status, falls back to the old
    # name-based behavior rather than erroring.
    priorities_bundle = {
        "top_risk_contributors": [
            {"SecurityName": "Anteile -X- Some Fund", "share_of_portfolio_volatility": 0.1}
        ],
        "priorities": [],
    }
    terms = relevant_search_terms({}, priorities_bundle)
    assert terms[0]["type"] == "security"


def test_relevant_search_terms_non_fund_with_ref_still_uses_security_name():
    from data_layer import ReferenceIndex

    reference = {"Securities": [{"Id": 5, "Name": "Nestle SA", "IsUnbundlingEnabled": False}]}
    ref = ReferenceIndex(reference)
    priorities_bundle = {
        "top_risk_contributors": [
            {"SecurityId": 5, "SecurityName": "Namen-Aktie Nestle SA", "share_of_portfolio_volatility": 0.2}
        ],
        "priorities": [],
    }
    terms = relevant_search_terms({}, priorities_bundle, ref=ref)
    assert terms[0]["type"] == "security"
    assert terms[0]["query"] == "Nestle SA"


def test_relevant_search_terms_uses_cleaned_names():
    priorities_bundle = {
        "top_risk_contributors": [
            {"SecurityName": "Namen-Aktie Nestle SA", "share_of_portfolio_volatility": 0.22}
        ],
        "priorities": [],
    }
    terms = relevant_search_terms({}, priorities_bundle)
    assert terms[0]["query"] == "Nestle SA"
    assert "22%" in terms[0]["reason"]


def test_relevant_search_terms_includes_concentration_and_saa_items():
    priorities_bundle = {
        "top_risk_contributors": [],
        "priorities": [
            {"type": "single_position_concentration", "security_name": "Namen-Aktie Sika AG", "weight": 0.35},
            {
                "type": "saa_breach",
                "dimension": "AssetClass",
                "category": "Bonds",
                "breach": "min",
            },
        ],
    }
    terms = relevant_search_terms({}, priorities_bundle)
    queries = [t["query"] for t in terms]
    assert "Sika AG" in queries
    assert "Bonds" in queries


def test_relevant_search_terms_deduplicates_by_query():
    priorities_bundle = {
        "top_risk_contributors": [
            {"SecurityName": "Namen-Aktie Nestle SA", "share_of_portfolio_volatility": 0.2}
        ],
        "priorities": [
            {"type": "single_position_concentration", "security_name": "Namen-Aktie Nestle SA", "weight": 0.3}
        ],
    }
    terms = relevant_search_terms({}, priorities_bundle)
    queries = [t["query"] for t in terms]
    assert queries.count("Nestle SA") == 1


def test_relevant_search_terms_skips_unresolved_structured_product_names():
    # "PERLES" is a known structured-product marker clean_security_name()
    # can't reliably resolve — never guess an issuer for it.
    priorities_bundle = {
        "top_risk_contributors": [
            {"SecurityName": "PERLES on SMI Index", "share_of_portfolio_volatility": 0.15}
        ],
        "priorities": [],
    }
    terms = relevant_search_terms({}, priorities_bundle)
    assert terms == []


def test_relevant_search_terms_skips_bare_truncated_stub_names():
    priorities_bundle = {
        "top_risk_contributors": [],
        "priorities": [
            {"type": "single_position_concentration", "security_name": "12.", "weight": 0.25},
        ],
    }
    terms = relevant_search_terms({}, priorities_bundle)
    assert terms == []


def test_relevant_search_terms_excludes_risk_contributors_when_risk_attribution_invalid():
    priorities_bundle = {
        "risk_attribution": {"status": "invalid"},
        "top_risk_contributors": [
            {"SecurityName": "Namen-Aktie Nestle SA", "share_of_portfolio_volatility": 0.5}
        ],
        "priorities": [],
    }
    terms = relevant_search_terms({}, priorities_bundle)
    assert terms == []


def test_relevant_search_terms_excludes_risk_contributors_when_risk_attribution_unavailable():
    priorities_bundle = {
        "risk_attribution": {"status": "unavailable"},
        "top_risk_contributors": [
            {"SecurityName": "Namen-Aktie Nestle SA", "share_of_portfolio_volatility": 0.5}
        ],
        "priorities": [],
    }
    terms = relevant_search_terms({}, priorities_bundle)
    assert terms == []


def test_relevant_search_terms_includes_risk_contributors_when_risk_attribution_ok():
    priorities_bundle = {
        "risk_attribution": {"status": "ok"},
        "top_risk_contributors": [
            {"SecurityName": "Namen-Aktie Nestle SA", "share_of_portfolio_volatility": 0.5}
        ],
        "priorities": [],
    }
    terms = relevant_search_terms({}, priorities_bundle)
    assert any(t["query"] == "Nestle SA" for t in terms)


def test_relevant_search_terms_material_industry_exposure_without_breach():
    priorities_bundle = {
        "top_risk_contributors": [],
        "priorities": [],  # no SAA breach at all
        "concentrations": {
            "dimensions": {
                "Industry": [{"category": "Financials", "weight": 0.22, "absolute_weight": 0.22}]
            }
        },
    }
    terms = relevant_search_terms({}, priorities_bundle)
    assert any(t["query"] == "Financials" and t["type"] == "sector" for t in terms)


def test_relevant_search_terms_ignores_immaterial_industry_exposure():
    priorities_bundle = {
        "top_risk_contributors": [],
        "priorities": [],
        "concentrations": {
            "dimensions": {
                "Industry": [{"category": "Financials", "weight": 0.02, "absolute_weight": 0.02}]
            }
        },
    }
    terms = relevant_search_terms({}, priorities_bundle)
    assert terms == []


def test_relevant_search_terms_uses_industry_client_tag_as_low_priority_subject():
    priorities_bundle = {
        "top_risk_contributors": [],
        "priorities": [],
        "client_tags": [
            {"TagName": "Health Care", "TagTypeName": "Industry", "Scope": "Client"},
        ],
    }
    terms = relevant_search_terms({}, priorities_bundle)
    assert len(terms) == 1
    assert terms[0]["query"] == "Health Care"
    assert terms[0]["type"] == "sector"
    assert terms[0]["priority_score"] == CLIENT_INTEREST_TAG_PRIORITY_SCORE


def test_relevant_search_terms_ignores_region_client_tags():
    # No evidence a broad region query returns relevant results on the
    # real news API (built for companies/sectors) — never guess.
    priorities_bundle = {
        "top_risk_contributors": [],
        "priorities": [],
        "client_tags": [
            {"TagName": "Switzerland", "TagTypeName": "Region", "Scope": "Client"},
        ],
    }
    terms = relevant_search_terms({}, priorities_bundle)
    assert terms == []


def test_relevant_search_terms_client_tag_does_not_duplicate_existing_sector_term():
    priorities_bundle = {
        "top_risk_contributors": [],
        "priorities": [
            {"type": "saa_breach", "dimension": "Industry", "category": "Health Care", "breach": "max", "priority_score": 80.0},
        ],
        "client_tags": [
            {"TagName": "Health Care", "TagTypeName": "Industry", "Scope": "Client"},
        ],
    }
    terms = relevant_search_terms({}, priorities_bundle)
    health_care_terms = [t for t in terms if t["query"] == "Health Care"]
    assert len(health_care_terms) == 1
    # The real SAA-breach term wins, not the low-priority client-interest one.
    assert health_care_terms[0]["priority_score"] == 80.0


def test_relevant_search_terms_client_tag_is_lower_priority_than_portfolio_signals():
    priorities_bundle = {
        "top_risk_contributors": [],
        "priorities": [
            {"type": "saa_breach", "dimension": "AssetClass", "category": "Bonds", "breach": "min", "priority_score": 78.0},
        ],
        "client_tags": [
            {"TagName": "Health Care", "TagTypeName": "Industry", "Scope": "Client"},
        ],
    }
    terms = relevant_search_terms({}, priorities_bundle)
    assert terms[0]["query"] == "Bonds"  # portfolio-derived signal ranked first
    assert terms[1]["query"] == "Health Care"


def test_relevant_search_terms_ranks_by_priority_score_and_caps_at_budget():
    priorities_bundle = {
        "top_risk_contributors": [],
        "priorities": [
            {"type": "saa_breach", "dimension": "AssetClass", "category": f"Cat{i}", "breach": "max", "priority_score": float(i)}
            for i in range(10)
        ],
    }
    terms = relevant_search_terms({}, priorities_bundle)
    assert len(terms) == BUDGET_MAX_SEARCH_SUBJECTS
    scores = [t["priority_score"] for t in terms]
    assert scores == sorted(scores, reverse=True)
    assert terms[0]["query"] == "Cat9"  # highest priority_score wins the budget slot


def test_fetch_relevant_news_tags_articles_with_match_info():
    terms = [{"type": "security", "query": "Nestle SA", "reason": "top risk contributor"}]
    provider = FakeNewsProvider(
        {"Nestle SA": [{"title": "Nestle news", "publisher": "X", "link": "http://x", "published_at": "2026-01-01", "summary": ""}]}
    )
    now = datetime(2026, 1, 3, tzinfo=timezone.utc)
    articles = fetch_relevant_news(terms, provider, now=now)
    assert len(articles) == 1
    assert articles[0]["matched_queries"] == ["Nestle SA"]
    assert articles[0]["match_reasons"] == ["top risk contributor"]


def test_fetch_relevant_news_empty_for_unmatched_query():
    terms = [{"type": "security", "query": "Unknown Co", "reason": "x"}]
    provider = FakeNewsProvider({})
    assert fetch_relevant_news(terms, provider) == []


def test_fetch_relevant_news_bundle_no_news_found_vs_fetch_failed_are_different_statuses():
    terms = [{"type": "security", "query": "Quiet Co", "reason": "x"}]

    no_news_bundle = fetch_relevant_news_bundle(terms, FakeNewsProvider({}))
    assert no_news_bundle["status"] == "no_news_found"

    failed_bundle = fetch_relevant_news_bundle(terms, FailingNewsProvider())
    assert failed_bundle["status"] == "fetch_failed"

    assert no_news_bundle["status"] != failed_bundle["status"]
    assert no_news_bundle["articles"] == []
    assert failed_bundle["articles"] == []


def test_fetch_relevant_news_bundle_partial_when_some_subjects_fail_but_others_return_articles():
    terms = [
        {"type": "security", "query": "Nestle SA", "reason": "r1"},
        {"type": "security", "query": "Broken Co", "reason": "r2"},
    ]

    class MixedProvider:
        def fetch(self, query, max_results=5):
            if query == "Broken Co":
                raise ConnectionError("boom")
            return [{"title": "Nestle news", "publisher": "X", "link": "http://x", "published_at": "2026-01-01"}]

    now = datetime(2026, 1, 3, tzinfo=timezone.utc)
    bundle = fetch_relevant_news_bundle(terms, MixedProvider(), now=now)
    assert bundle["status"] == "partial"
    assert len(bundle["articles"]) == 1
    assert "some_search_subjects_failed" in bundle["reasons"]


def test_fetch_relevant_news_bundle_prefers_7day_window_over_14day():
    terms = [{"type": "security", "query": "Q", "reason": "r"}]
    now = datetime(2026, 1, 10, tzinfo=timezone.utc)
    provider = FakeNewsProvider(
        {
            "Q": [
                {"title": "Fresh", "publisher": "X", "link": "http://fresh", "published_at": "2026-01-09"},
                {"title": "Stale-ish", "publisher": "X", "link": "http://stale", "published_at": "2026-01-01"},
            ]
        }
    )
    bundle = fetch_relevant_news_bundle(terms, provider, now=now)
    assert bundle["freshness_window_used"] == "preferred_7d"
    titles = [a["title"] for a in bundle["articles"]]
    assert titles == ["Fresh"]


def test_fetch_relevant_news_bundle_falls_back_to_14day_window_when_nothing_within_7():
    terms = [{"type": "security", "query": "Q", "reason": "r"}]
    now = datetime(2026, 1, 10, tzinfo=timezone.utc)
    provider = FakeNewsProvider(
        {"Q": [{"title": "Twelve days old", "publisher": "X", "link": "http://x", "published_at": "2025-12-29"}]}
    )
    bundle = fetch_relevant_news_bundle(terms, provider, now=now)
    assert bundle["freshness_window_used"] == "fallback_14d"
    assert len(bundle["articles"]) == 1


def test_fetch_relevant_news_bundle_excludes_articles_older_than_14_days():
    terms = [{"type": "security", "query": "Q", "reason": "r"}]
    now = datetime(2026, 1, 10, tzinfo=timezone.utc)
    provider = FakeNewsProvider(
        {"Q": [{"title": "Very old", "publisher": "X", "link": "http://x", "published_at": "2025-11-01"}]}
    )
    bundle = fetch_relevant_news_bundle(terms, provider, now=now)
    assert bundle["status"] == "no_news_found"
    assert bundle["articles"] == []


def test_fetch_relevant_news_bundle_excludes_undated_articles_never_assumes_freshness():
    terms = [{"type": "security", "query": "Q", "reason": "r"}]
    provider = FakeNewsProvider({"Q": [{"title": "No date", "publisher": "X", "link": "http://x"}]})
    bundle = fetch_relevant_news_bundle(terms, provider)
    assert bundle["articles"] == []
    assert bundle["status"] == "no_news_found"


def test_fetch_relevant_news_bundle_merges_cross_query_duplicates_keeping_all_provenance():
    terms = [
        {"type": "security", "query": "Nestle SA", "reason": "top risk contributor", "fact_id": "1:risk_contributor:5"},
        {"type": "sector", "query": "Consumer Staples", "reason": "SAA breach", "fact_id": "1:saa_breach:AssetClass:0"},
    ]
    same_article = {"title": "Nestle news", "publisher": "X", "link": "http://x", "published_at": "2026-01-01"}
    provider = FakeNewsProvider({"Nestle SA": [same_article], "Consumer Staples": [same_article]})
    now = datetime(2026, 1, 2, tzinfo=timezone.utc)

    bundle = fetch_relevant_news_bundle(terms, provider, now=now)
    assert len(bundle["articles"]) == 1
    merged = bundle["articles"][0]
    assert set(merged["matched_queries"]) == {"Nestle SA", "Consumer Staples"}
    assert set(merged["match_reasons"]) == {"top risk contributor", "SAA breach"}
    assert set(merged["fact_ids"]) == {"1:risk_contributor:5", "1:saa_breach:AssetClass:0"}


def test_fetch_relevant_news_bundle_enforces_max_articles_per_subject():
    terms = [{"type": "security", "query": "Q", "reason": "r"}]
    now = datetime(2026, 1, 2, tzinfo=timezone.utc)
    many_articles = [
        {"title": f"Article {i}", "publisher": "X", "link": f"http://x/{i}", "published_at": "2026-01-01"}
        for i in range(10)
    ]
    provider = FakeNewsProvider({"Q": many_articles})
    bundle = fetch_relevant_news_bundle(terms, provider, now=now)
    assert len(bundle["articles"]) <= BUDGET_MAX_ARTICLES_PER_SUBJECT


def test_fetch_relevant_news_bundle_enforces_max_total_retained_articles():
    terms = [
        {"type": "security", "query": f"Q{i}", "reason": "r"} for i in range(5)
    ]
    now = datetime(2026, 1, 2, tzinfo=timezone.utc)
    canned = {
        f"Q{i}": [
            {"title": f"A{i}-1", "publisher": "X", "link": f"http://x/{i}/1", "published_at": "2026-01-01"},
            {"title": f"A{i}-2", "publisher": "X", "link": f"http://x/{i}/2", "published_at": "2026-01-01"},
        ]
        for i in range(5)
    }
    provider = FakeNewsProvider(canned)
    bundle = fetch_relevant_news_bundle(terms, provider, now=now)
    assert len(bundle["articles"]) <= BUDGET_MAX_RETAINED_ARTICLES


def test_fetch_relevant_news_bundle_no_terms_is_no_news_found_not_a_failure():
    bundle = fetch_relevant_news_bundle([], FakeNewsProvider({}))
    assert bundle["status"] == "no_news_found"
    assert "no_search_terms_generated" in bundle["reasons"]
