from helpers import first_client
from analysis_layer.concentration import (
    dimension_concentration,
    largest_single_positions,
    non_base_currency_exposure,
)


def _portfolio_and_ref():
    client, ref = first_client()
    return client["Portfolios"][0], ref


def test_largest_single_positions_ranks_by_weight():
    portfolio, _ = _portfolio_and_ref()
    ranked = largest_single_positions(portfolio, n=5)
    # Fixture: Nestle 35%, fund 25%.
    assert ranked[0]["SecurityName"] == "Nestle SA"
    assert ranked[0]["PortfolioValuePercentage"] == 0.35
    assert ranked[1]["SecurityName"] == "Global Balanced Fund"


def test_largest_single_positions_empty_portfolio():
    assert largest_single_positions({"SecurityPositions": []}, n=5) == []


def test_dimension_concentration_uses_look_through():
    portfolio, ref = _portfolio_and_ref()
    ranked = dimension_concentration(portfolio, "AssetClass", ref, n=5)
    categories = {row["category"]: row["weight"] for row in ranked}
    # Same numbers as the SAA actual_exposure test: Shares ~0.50, Bonds ~0.10.
    assert abs(categories["Shares"] - 0.50) < 1e-6
    assert abs(categories["Bonds"] - 0.10) < 1e-6


def test_dimension_concentration_respects_n():
    portfolio, ref = _portfolio_and_ref()
    ranked = dimension_concentration(portfolio, "AssetClass", ref, n=1)
    assert len(ranked) == 1
    assert ranked[0]["category"] == "Shares"  # the largest bucket


# --- non_base_currency_exposure ---


def test_non_base_currency_exposure_sums_positions_in_other_currencies():
    portfolio = {
        "PortfolioCurrency": "CHF",
        "SecurityPositions": [
            {"SecurityId": 1, "Currency": "CHF", "PortfolioValuePercentage": 0.6},
            {"SecurityId": 2, "Currency": "USD", "PortfolioValuePercentage": 0.3},
        ],
        "AccountPositions": [
            {"AccountName": "EUR cash", "Currency": "EUR", "PortfolioValuePercentage": 0.1},
        ],
    }
    assert abs(non_base_currency_exposure(portfolio) - 0.4) < 1e-9


def test_non_base_currency_exposure_all_base_currency_is_zero():
    portfolio = {
        "PortfolioCurrency": "CHF",
        "SecurityPositions": [{"SecurityId": 1, "Currency": "CHF", "PortfolioValuePercentage": 1.0}],
    }
    assert non_base_currency_exposure(portfolio) == 0.0


def test_non_base_currency_exposure_none_without_portfolio_currency():
    portfolio = {"SecurityPositions": [{"SecurityId": 1, "Currency": "USD", "PortfolioValuePercentage": 1.0}]}
    assert non_base_currency_exposure(portfolio) is None


def test_non_base_currency_exposure_uses_absolute_weight_for_short_positions():
    portfolio = {
        "PortfolioCurrency": "CHF",
        "SecurityPositions": [{"SecurityId": 1, "Currency": "USD", "PortfolioValuePercentage": -0.2}],
    }
    assert non_base_currency_exposure(portfolio) == 0.2
