from analysis_layer.performance import (
    current_risk_return_snapshot,
    performance_trend,
    risk_contributor_analysis,
    top_risk_contributors,
)


def portfolio():
    return {
        "Volatility": 0.10,
        "ExpectedReturn": 0.04,
        "ValueAtRisk": 0.07,
        "PerformanceHistory": [
            {"Date": "2026-01-01", "Value": 100.0},
            {"Date": "2026-04-01", "Value": 110.0},
            {"Date": "2026-07-01", "Value": 105.0},
        ],
        "SecurityPositions": [
            {
                "SecurityId": 1,
                "SecurityName": "A",
                "PortfolioValuePercentage": 0.60,
                "ContributionVolatility": 0.07,
            }
        ],
        "AccountPositions": [
            {
                "AccountName": "Cash CHF",
                "PortfolioValuePercentage": 0.40,
                "ContributionVolatility": 0.03,
            }
        ],
    }


def test_performance_sorts_unsorted_history_and_calls_it_value_change():
    p = portfolio()
    p["PerformanceHistory"] = [p["PerformanceHistory"][2], p["PerformanceHistory"][0], p["PerformanceHistory"][1]]
    result = performance_trend(p)
    assert result["latest_date"] == "2026-07-01"
    assert result["semantics"] == "portfolio_value_change_not_confirmed_return"
    assert result["change_since_previous_point"] == -5.0


def test_performance_ytd_is_only_used_when_explicitly_provided():
    p = portfolio()
    assert performance_trend(p)["performance_ytd"] is None
    p["PerformanceYTD"] = 0.08
    result = performance_trend(p)
    assert result["performance_ytd"] == 0.08
    assert result["performance_ytd_source"] == "provided"


def test_current_risk_return_keeps_expected_return_forward_looking():
    result = current_risk_return_snapshot(portfolio())
    assert result["expected_return"] == 0.04
    assert result["expected_return_semantics"] == "forward_looking_expected_return"


def test_risk_attribution_includes_account_position():
    result = risk_contributor_analysis(portfolio(), n=5)
    assert result["status"] == "ok"
    assert len(result["contributors"]) == 2
    assert any(x["position_type"] == "account" for x in result["contributors"])


def test_invalid_risk_attribution_emits_no_ranking():
    p = portfolio()
    p["SecurityPositions"][0]["ContributionVolatility"] = 9999.0
    result = risk_contributor_analysis(p)
    assert result["status"] == "invalid"
    assert result["contributors"] == []
    assert top_risk_contributors(p) == []


def test_negative_contribution_is_a_risk_reducer_not_top_contributor():
    p = portfolio()
    p["SecurityPositions"] = [
        {"SecurityName": "A", "PortfolioValuePercentage": 0.7, "ContributionVolatility": 0.12},
        {"SecurityName": "Hedge", "PortfolioValuePercentage": 0.1, "ContributionVolatility": -0.04},
    ]
    p["AccountPositions"] = [{"AccountName": "Cash", "PortfolioValuePercentage": 0.2, "ContributionVolatility": 0.02}]
    result = risk_contributor_analysis(p)
    assert result["status"] == "ok"
    assert result["risk_reducers"][0]["SecurityName"] == "Hedge"
