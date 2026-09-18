from helpers import first_client
from analysis_layer.concentration import largest_single_positions, dimension_concentration


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
