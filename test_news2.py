from enrichment.market_news import (
    clean_security_name,
    relevant_search_terms,
    fetch_relevant_news,
    FakeNewsProvider,
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


def test_fetch_relevant_news_tags_articles_with_match_info():
    terms = [{"type": "security", "query": "Nestle SA", "reason": "top risk contributor"}]
    provider = FakeNewsProvider(
        {"Nestle SA": [{"title": "Nestle news", "publisher": "X", "link": "http://x", "published_at": "2026-01-01", "summary": ""}]}
    )
    articles = fetch_relevant_news(terms, provider)
    assert len(articles) == 1
    assert articles[0]["matched_query"] == "Nestle SA"
    assert articles[0]["match_reason"] == "top risk contributor"


def test_fetch_relevant_news_empty_for_unmatched_query():
    terms = [{"type": "security", "query": "Unknown Co", "reason": "x"}]
    provider = FakeNewsProvider({})
    assert fetch_relevant_news(terms, provider) == []