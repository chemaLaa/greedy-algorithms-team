from synthesis.prompt_builder import (
    build_prompt,
    context_to_prose,
    _format_client_and_portfolio,
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
        "priorities": [],
        "top_risk_contributors": [],
        "change_since_last_interaction": {"source": "state_diff", "is_first_interaction": True, "details": {}},
        "house_view_alignment": [],
        "market_news": [],
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
                "type": "saa_deviation",
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
    text = _format_priorities([{"type": "concentration", "security_name": "Nestle SA", "weight": 0.35}])
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
         "relative_position": "aligned", "client_actual": 0.5, "client_target": 0.5, "rationale": "r"},
        {"category": "Bonds", "dimension": "AssetClass", "house_view_stance": "underweight",
         "relative_position": "underexposed", "client_actual": 0.1, "client_target": 0.3, "rationale": "r"},
    ]
    text = _format_house_view(alignment)
    assert "Bonds" in text
    assert "Already aligned with the house view on: Shares" in text


def test_house_view_caps_actionable_items():
    alignment = [
        {"category": f"Cat{i}", "dimension": "AssetClass", "house_view_stance": "overweight",
         "relative_position": "underexposed", "client_actual": 0.1, "client_target": 0.3, "rationale": "r"}
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


# --- integration: context_to_prose and build_prompt ---


def test_context_to_prose_has_all_expected_keys():
    fragments = context_to_prose(_minimal_context())
    assert set(fragments.keys()) == {
        "client_and_portfolio", "performance", "priorities", "risk_contributors",
        "change_since_last_interaction", "house_view", "news",
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


def test_build_prompt_user_message_contains_client_name():
    prompt = build_prompt(_minimal_context())
    assert "Anna Meier" in prompt["messages"][0]["content"]
