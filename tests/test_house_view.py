from enrichment.house_view import compare_portfolio_to_house_view

TEST_HOUSE_VIEW = [
    {"dimension": "AssetClass", "category": "Shares", "stance": "overweight", "rationale": "r1"},
    {"dimension": "AssetClass", "category": "Bonds", "stance": "underweight", "rationale": "r2"},
    {"dimension": "AssetClass", "category": "Real estate", "stance": "neutral", "rationale": "r3"},
    {"dimension": "AssetClass", "category": "Liquidity", "stance": "overweight", "rationale": "r4"},
]


def _portfolio(shares_dev, bonds_dev, no_target_dev=None):
    return {
        "saa_deviations": {
            "AssetClass": [
                {"category": "Shares", "actual": 0.5 + shares_dev, "target": 0.5, "deviation_from_target": shares_dev},
                {"category": "Bonds", "actual": 0.4 + bonds_dev, "target": 0.4, "deviation_from_target": bonds_dev},
                {"category": "Real estate", "actual": 0.05, "target": 0.05, "deviation_from_target": 0.0},
                # no "Liquidity" row at all — category house view has no matching data
            ]
        }
    }


def test_overweight_stance_with_positive_deviation_is_aligned():
    portfolio = _portfolio(shares_dev=0.05, bonds_dev=0.0)
    result = compare_portfolio_to_house_view(portfolio, TEST_HOUSE_VIEW)
    shares = next(r for r in result if r["category"] == "Shares")
    assert shares["relative_position"] == "aligned"


def test_overweight_stance_with_negative_deviation_is_underexposed():
    portfolio = _portfolio(shares_dev=-0.05, bonds_dev=0.0)
    result = compare_portfolio_to_house_view(portfolio, TEST_HOUSE_VIEW)
    shares = next(r for r in result if r["category"] == "Shares")
    assert shares["relative_position"] == "underexposed"


def test_underweight_stance_with_negative_deviation_is_aligned():
    portfolio = _portfolio(shares_dev=0.0, bonds_dev=-0.03)
    result = compare_portfolio_to_house_view(portfolio, TEST_HOUSE_VIEW)
    bonds = next(r for r in result if r["category"] == "Bonds")
    assert bonds["relative_position"] == "aligned"


def test_underweight_stance_with_positive_deviation_is_overexposed():
    portfolio = _portfolio(shares_dev=0.0, bonds_dev=0.03)
    result = compare_portfolio_to_house_view(portfolio, TEST_HOUSE_VIEW)
    bonds = next(r for r in result if r["category"] == "Bonds")
    assert bonds["relative_position"] == "overexposed"


def test_neutral_stance_is_not_applicable():
    portfolio = _portfolio(shares_dev=0.0, bonds_dev=0.0)
    result = compare_portfolio_to_house_view(portfolio, TEST_HOUSE_VIEW)
    real_estate = next(r for r in result if r["category"] == "Real estate")
    assert real_estate["relative_position"] == "not_applicable"


def test_category_with_no_matching_saa_row_is_skipped():
    portfolio = _portfolio(shares_dev=0.0, bonds_dev=0.0)
    result = compare_portfolio_to_house_view(portfolio, TEST_HOUSE_VIEW)
    categories = [r["category"] for r in result]
    assert "Liquidity" not in categories  # no SAA row for it in this portfolio


def test_empty_portfolio_returns_empty_list():
    result = compare_portfolio_to_house_view({}, TEST_HOUSE_VIEW)
    assert result == []


def test_exact_zero_deviation_is_aligned_not_overexposed_for_underweight():
    # Real bug found via a live client (Spock): actual=0.0%, target=0.0%
    # for an "underweight" house view category incorrectly came back as
    # "overexposed" — deviation is exactly 0, which strict "< 0" excludes.
    portfolio = _portfolio(shares_dev=0.0, bonds_dev=0.0)
    result = compare_portfolio_to_house_view(portfolio, TEST_HOUSE_VIEW)
    bonds = next(r for r in result if r["category"] == "Bonds")
    assert bonds["relative_position"] == "aligned"


def test_exact_zero_deviation_is_aligned_not_underexposed_for_overweight():
    # Symmetric case for "overweight" stance.
    portfolio = _portfolio(shares_dev=0.0, bonds_dev=0.0)
    result = compare_portfolio_to_house_view(portfolio, TEST_HOUSE_VIEW)
    shares = next(r for r in result if r["category"] == "Shares")
    assert shares["relative_position"] == "aligned"