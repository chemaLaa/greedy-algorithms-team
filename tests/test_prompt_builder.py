from synthesis.prompt_builder import (
    build_prompt,
    context_to_prose,
    _format_attribution_caveat,
    _format_client_and_portfolio,
    _format_client_notes,
    _format_performance,
    _format_priorities,
    _format_risk_contributors,
    _format_change,
    _format_house_view,
    _format_news,
)


def _minimal_context(**overrides):
    base = {
        "client": {"name": "Anna Meier", "risk_profile": "Balanced", "esg_profile": None},
        "portfolio": {
            "portfolio_id": 1,
            "portfolio_name": "Vorsorge Indiv",
            "value": 500000,
            "reporting_currency": "CHF",
            "performance_trend": {
                "latest_value": 500000,
                "previous_value": 510000,
                "change_since_previous_point": -10000,
                "change_since_previous_point_pct": -10000 / 510000,
                "latest_date": "2026-09-01",
                "previous_date": "2026-08-01",
            },
        },
        "client_notes": [],
        "priorities": [],
        "top_risk_contributors": [],
        "change_since_last_interaction": {"source": "state_diff", "is_first_interaction": True, "details": {}},
        "house_view_alignment": [],
        "market_news": [],
        "attribution_caveat": {
            "liquidity_ratio": 0.05,
            "has_holdings_based_drivers": True,
            "non_base_currency_exposure": 0.0,
        },
    }
    base.update(overrides)
    return base


# --- _format_client_and_portfolio ---


def test_client_and_portfolio_includes_name_and_risk_profile():
    text = _format_client_and_portfolio(_minimal_context())
    assert "Anna Meier" in text
    assert "Balanced" in text
    assert "500,000" in text
    assert "CHF" in text


def test_client_and_portfolio_omits_esg_when_none():
    text = _format_client_and_portfolio(_minimal_context())
    assert "ESG" not in text


def test_client_and_portfolio_includes_esg_when_present():
    context = _minimal_context()
    context["client"]["esg_profile"] = "Yes"
    text = _format_client_and_portfolio(context)
    assert "ESG preference: Yes" in text


def test_client_and_portfolio_handles_missing_value():
    context = _minimal_context()
    context["portfolio"]["value"] = None
    text = _format_client_and_portfolio(context)
    assert "unavailable" in text


# --- _format_client_notes ---


def test_client_notes_empty():
    assert "No advisory notes" in _format_client_notes([])


def test_client_notes_formats_date_and_text():
    text = _format_client_notes([{"date": "2026-09-05T09:16:32", "text": "No direct positions in fossil fuels, please."}])
    assert "2026-09-05" in text
    assert "No direct positions in fossil fuels" in text
    # The time-of-day component is noise for the model, not signal.
    assert "09:16:32" not in text


def test_client_notes_lists_most_recent_first_as_given():
    # context_builder is responsible for sorting; this formatter just
    # renders in the order it's handed, so this locks in that contract.
    notes = [
        {"date": "2026-09-12T13:25:53", "text": "Newest note."},
        {"date": "2024-09-17T09:16:32", "text": "Oldest note."},
    ]
    text = _format_client_notes(notes)
    assert text.index("Newest note.") < text.index("Oldest note.")


def test_client_notes_handles_non_iso_date_gracefully():
    text = _format_client_notes([{"date": "unparseable", "text": "Something the advisor wrote."}])
    assert "unparseable" in text
    assert "Something the advisor wrote." in text


# --- _format_performance ---


def test_performance_formats_change():
    trend = _minimal_context()["portfolio"]["performance_trend"]
    text = _format_performance(trend)
    assert "510,000" in text
    assert "500,000" in text
    assert "-2.0%" in text


def test_performance_handles_none():
    assert "No prior performance history" in _format_performance(None)


def test_performance_handles_insufficient_history():
    assert "No prior performance history" in _format_performance({"change_since_previous_point": None})


# --- _format_attribution_caveat ---


def test_attribution_caveat_none_returns_placeholder_not_empty():
    text = _format_attribution_caveat(None)
    assert text
    assert "No data-availability" in text


def test_attribution_caveat_flags_high_liquidity():
    text = _format_attribution_caveat(
        {"liquidity_ratio": 0.95, "has_holdings_based_drivers": True, "non_base_currency_exposure": 0.0}
    )
    assert "95%" in text
    assert "liquid" in text.lower()


def test_attribution_caveat_flags_no_holdings_based_drivers():
    text = _format_attribution_caveat(
        {"liquidity_ratio": 0.05, "has_holdings_based_drivers": False, "non_base_currency_exposure": 0.0}
    )
    assert "No security-level risk-contribution data" in text
    assert "unless another fact" in text


def test_attribution_caveat_flags_material_fx_exposure_without_claiming_an_effect():
    text = _format_attribution_caveat(
        {"liquidity_ratio": 0.05, "has_holdings_based_drivers": True, "non_base_currency_exposure": 0.6}
    )
    assert "60%" in text
    assert "do not estimate" in text.lower()


def test_attribution_caveat_low_liquidity_and_holdings_present_has_no_caveats():
    text = _format_attribution_caveat(
        {"liquidity_ratio": 0.05, "has_holdings_based_drivers": True, "non_base_currency_exposure": 0.0}
    )
    assert "No specific data-availability caveats" in text


def test_attribution_caveat_fully_liquid_and_no_drivers_flags_both():
    # The exact scenario this whole mechanism exists for: a heavily liquid
    # portfolio with no security-level data to blame a decline on.
    text = _format_attribution_caveat(
        {"liquidity_ratio": 1.0, "has_holdings_based_drivers": False, "non_base_currency_exposure": None}
    )
    assert "100%" in text
    assert "liquid" in text.lower()
    assert "No security-level risk-contribution data" in text


# --- _format_priorities ---


def test_priorities_empty_list():
    assert "No active" in _format_priorities([])


def test_priorities_formats_violation():
    text = _format_priorities([{"type": "violation", "severity": "Error", "description": "Too risky"}])
    assert "[Error] Too risky" in text


def test_priorities_formats_saa_deviation_below():
    text = _format_priorities(
        [
            {
                "type": "saa_breach",
                "category": "Bonds",
                "dimension": "AssetClass",
                "actual": 0.10,
                "target": 0.40,
                "breach": "min",
            }
        ]
    )
    assert "Bonds" in text
    assert "10.0%" in text
    assert "40.0%" in text
    assert "below" in text


def test_priorities_formats_concentration():
    text = _format_priorities([{"type": "single_position_concentration", "security_name": "Nestle SA", "weight": 0.35}])
    assert "Nestle SA" in text


def test_priorities_formats_concentration_cleans_raw_security_name():
    text = _format_priorities(
        [{"type": "single_position_concentration", "security_name": "Namen-Aktie Nestle SA", "weight": 0.35}]
    )
    assert "Namen-Aktie" not in text
    assert "Nestle SA" in text
    assert "35.0%" in text


# --- _format_risk_contributors ---


def test_risk_contributors_empty():
    assert "No risk-contribution data" in _format_risk_contributors([])


def test_risk_contributors_formats_share():
    text = _format_risk_contributors(
        [{"SecurityName": "Nestle SA", "share_of_portfolio_volatility": 0.22}]
    )
    assert "Nestle SA" in text
    assert "22%" in text


def test_risk_contributors_warns_against_treating_as_a_return_cause():
    # This is co-located with the fact itself (not just stated once in the
    # system prompt) precisely so a model summarizing this section can't
    # miss it.
    text = _format_risk_contributors([{"SecurityName": "Nestle SA", "share_of_portfolio_volatility": 0.22}])
    assert "not a confirmed explanation" in text


def test_risk_contributors_cleans_raw_security_name():
    text = _format_risk_contributors(
        [{"SecurityName": "Namen-Aktie Sika AG", "share_of_portfolio_volatility": 0.31}]
    )
    assert "Namen-Aktie" not in text
    assert "Sika AG" in text


def test_risk_contributors_handles_missing_share():
    text = _format_risk_contributors([{"SecurityName": "X", "share_of_portfolio_volatility": None}])
    assert "unknown share" in text


# --- _format_change ---


def test_change_first_interaction():
    change = {"source": "state_diff", "details": {"is_first_interaction": True}}
    text = _format_change(change)
    assert "first briefing" in text


def test_change_state_diff_with_new_and_resolved_violations():
    change = {
        "source": "state_diff",
        "details": {
            "is_first_interaction": False,
            "violations_new": ["RULE_A"],
            "violations_resolved": ["RULE_B"],
            "portfolio_value_change": None,
            "allocation_changes": {},
            "position_changes": {},
        },
    }
    text = _format_change(change)
    assert "RULE_A" in text
    assert "RULE_B" in text
    assert "New issues" in text
    assert "Resolved" in text


def test_change_state_diff_no_changes_at_all():
    change = {
        "source": "state_diff",
        "details": {
            "is_first_interaction": False,
            "violations_new": [],
            "violations_resolved": [],
            "portfolio_value_change": None,
            "allocation_changes": {},
            "position_changes": {},
        },
    }
    text = _format_change(change)
    assert "No material changes" in text


def test_change_note_proxy_with_no_comparison_point():
    change = {"source": "note_date_proxy", "details": {"since_date": None, "value_then": None}}
    text = _format_change(change)
    assert "No reliable comparison" in text


def test_change_note_proxy_with_estimate():
    change = {
        "source": "note_date_proxy",
        "details": {"since_date": "2026-08-01", "value_then": 100000, "change_pct": 0.05},
    }
    text = _format_change(change)
    assert "Approximate estimate" in text
    assert "+5.0%" in text


def test_change_handles_none():
    assert "No information available" in _format_change(None)


# --- _format_house_view ---


def test_house_view_leads_with_actionable_items():
    alignment = [
        {"category": "Shares", "dimension": "AssetClass", "house_view_stance": "overweight",
         "relative_position": "aligned", "client_actual": 0.55, "client_target": 0.5, "rationale": "r"},
        {"category": "Bonds", "dimension": "AssetClass", "house_view_stance": "underweight",
         "relative_position": "opposite", "client_actual": 0.1, "client_target": 0.3, "rationale": "r"},
    ]
    text = _format_house_view(alignment)
    assert "Bonds" in text
    assert "Already aligned with the house view on: Shares" in text


def test_house_view_caps_actionable_items():
    alignment = [
        {"category": f"Cat{i}", "dimension": "AssetClass", "house_view_stance": "overweight",
         "relative_position": "opposite", "client_actual": 0.1, "client_target": 0.3, "rationale": "r"}
        for i in range(10)
    ]
    text = _format_house_view(alignment, max_actionable=3)
    assert text.count("Cat") == 3


def test_house_view_empty():
    assert "No notable alignment" in _format_house_view([])


def test_house_view_skips_not_applicable_without_mentioning():
    alignment = [
        {"category": "Real estate", "dimension": "AssetClass", "house_view_stance": "neutral",
         "relative_position": "not_applicable", "client_actual": 0.05, "client_target": 0.05, "rationale": "r"},
    ]
    text = _format_house_view(alignment)
    assert "Real estate" not in text


def test_house_view_always_includes_precedence_note():
    # This must reach the LLM-facing text regardless of what's in
    # alignment — even an empty list.
    assert "suitability" in _format_house_view([]).lower()
    alignment = [
        {"category": "Shares", "dimension": "AssetClass", "house_view_stance": "overweight",
         "relative_position": "aligned", "client_actual": 0.55, "client_target": 0.5, "rationale": "r"},
    ]
    assert "suitability" in _format_house_view(alignment).lower()


def test_house_view_at_target_is_reported_separately_from_aligned():
    alignment = [
        {"category": "Shares", "dimension": "AssetClass", "house_view_stance": "overweight",
         "relative_position": "at_target", "client_actual": 0.5, "client_target": 0.5, "rationale": "r"},
    ]
    text = _format_house_view(alignment)
    assert "Shares" in text
    assert "Already aligned with the house view on" not in text
    assert "target" in text.lower()


def test_house_view_notes_mock_data_when_any_row_is_mock():
    alignment = [
        {"category": "Shares", "dimension": "AssetClass", "house_view_stance": "overweight",
         "relative_position": "aligned", "client_actual": 0.55, "client_target": 0.5, "rationale": "r",
         "is_mock": True},
    ]
    text = _format_house_view(alignment)
    assert "MOCK" in text


def test_house_view_no_mock_note_when_not_mock():
    alignment = [
        {"category": "Shares", "dimension": "AssetClass", "house_view_stance": "overweight",
         "relative_position": "aligned", "client_actual": 0.55, "client_target": 0.5, "rationale": "r",
         "is_mock": False},
    ]
    text = _format_house_view(alignment)
    assert "MOCK" not in text


# --- _format_news ---


def test_news_empty():
    assert "No relevant market news" in _format_news([])


def test_news_formats_article():
    text = _format_news(
        [{"title": "Test headline", "publisher": "Reuters", "matched_query": "Nestle SA", "match_reason": "top contributor"}]
    )
    assert "Test headline" in text
    assert "Reuters" in text
    assert "Nestle SA" in text


def test_news_formats_article_with_merged_matched_queries():
    text = _format_news(
        [{
            "title": "Test headline", "publisher": "Reuters",
            "matched_queries": ["Nestle SA", "Consumer Staples"],
            "match_reasons": ["top contributor", "SAA breach"],
        }]
    )
    assert "Nestle SA" in text
    assert "Consumer Staples" in text


def test_news_distinguishes_fetch_failed_from_no_news_found():
    failed_text = _format_news([], {"status": "fetch_failed", "reasons": ["all_search_subjects_failed"]})
    no_news_text = _format_news([], {"status": "no_news_found", "reasons": []})
    assert failed_text != no_news_text
    assert "fail" in failed_text.lower()
    assert "no relevant market news" in no_news_text.lower()


# --- integration: context_to_prose and build_prompt ---


def test_context_to_prose_has_all_expected_keys():
    fragments = context_to_prose(_minimal_context())
    assert set(fragments.keys()) == {
        "client_and_portfolio", "client_notes", "performance", "attribution_caveat",
        "priorities", "risk_contributors", "change_since_last_interaction", "house_view", "news",
    }


def test_build_prompt_returns_system_and_messages():
    prompt = build_prompt(_minimal_context())
    assert "system" in prompt
    assert "messages" in prompt
    assert prompt["messages"][0]["role"] == "user"


def test_build_prompt_system_mentions_required_sections():
    prompt = build_prompt(_minimal_context())
    system = prompt["system"]
    assert "recent_development" in system
    assert "health_check" in system
    assert "outlook_and_actions" in system


def test_build_prompt_system_forbids_unsupported_attribution():
    # Normalize whitespace: SYSTEM_PROMPT wraps long bullets across source
    # lines with backslash-continuation, which leaves literal double
    # spaces at each wrap point — irrelevant to the model, but a trap for
    # a naive exact-substring test.
    system = " ".join(build_prompt(_minimal_context())["system"].split())
    assert "isn't identifiable from the available data" in system
    assert "cash flows, fees, and currency movements" in system


def test_build_prompt_user_message_includes_attribution_caveat_section():
    prompt = build_prompt(
        _minimal_context(
            attribution_caveat={
                "liquidity_ratio": 1.0,
                "has_holdings_based_drivers": False,
                "non_base_currency_exposure": None,
            }
        )
    )
    content = prompt["messages"][0]["content"]
    assert "DATA AVAILABILITY FOR ATTRIBUTING THIS CHANGE" in content
    assert "100%" in content
    assert "No security-level risk-contribution data" in content


def test_build_prompt_user_message_includes_client_notes_section():
    prompt = build_prompt(
        _minimal_context(client_notes=[{"date": "2026-09-12", "text": "No direct positions in fossil fuels, please."}])
    )
    content = prompt["messages"][0]["content"]
    assert "CLIENT NOTES / CIRCUMSTANCES" in content
    assert "No direct positions in fossil fuels" in content


def test_build_prompt_system_mentions_client_circumstances_and_staleness_judgment():
    system = " ".join(build_prompt(_minimal_context())["system"].split())
    assert "CLIENT NOTES" in system
    assert "still applies" in system or "still relevant" in system


def test_build_prompt_user_message_contains_client_name():
    prompt = build_prompt(_minimal_context())
    assert "Anna Meier" in prompt["messages"][0]["content"]