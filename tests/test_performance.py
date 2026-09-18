from helpers import first_client
from analysis_layer.performance import performance_trend, top_risk_contributors


def _portfolio():
    client, ref = first_client()
    return client["Portfolios"][0]


def test_performance_trend_computes_change_between_last_two_points():
    portfolio = _portfolio()
    trend = performance_trend(portfolio)
    # Fixture: last two PerformanceHistory points are 510000 (2026-08-01)
    # then 500000 (2026-09-01).
    assert trend["latest_value"] == 500000
    assert trend["previous_value"] == 510000
    assert trend["change_since_previous_point"] == -10000
    assert abs(trend["change_since_previous_point_pct"] - (-10000 / 510000)) < 1e-9


def test_performance_trend_handles_missing_history():
    assert performance_trend({"PerformanceHistory": []}) == {
        "latest_value": None,
        "latest_date": None,
        "previous_value": None,
        "previous_date": None,
        "change_since_previous_point": None,
        "change_since_previous_point_pct": None,
        "performance_ytd": None,
        "months_of_history": 0,
    }


def test_performance_trend_handles_single_point():
    result = performance_trend({"PerformanceHistory": [{"Date": "2026-01-01", "Value": 100}]})
    assert result["latest_value"] == 100
    assert result["change_since_previous_point"] is None
    assert result["months_of_history"] == 1


def test_top_risk_contributors_ranks_by_contribution_volatility():
    portfolio = _portfolio()
    ranked = top_risk_contributors(portfolio, n=5)
    # Fixture: Nestle has ContributionVolatility 0.007, the fund 0.004.
    assert ranked[0]["SecurityName"] == "Nestle SA"
    assert ranked[1]["SecurityName"] == "Global Balanced Fund"


def test_top_risk_contributors_respects_n():
    portfolio = _portfolio()
    assert len(top_risk_contributors(portfolio, n=1)) == 1


def test_top_risk_contributors_share_is_none_without_total_volatility():
    portfolio = {"SecurityPositions": [{"SecurityName": "X", "ContributionVolatility": 0.01}]}
    ranked = top_risk_contributors(portfolio, n=5)
    assert ranked[0]["share_of_portfolio_volatility"] is None
