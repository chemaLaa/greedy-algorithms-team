from enrichment.house_view import (
    HOUSE_VIEW_PRECEDENCE_NOTE,
    MockHouseViewProvider,
    StaticHouseViewProvider,
    compare_portfolio_to_house_view,
    get_house_view,
)

TEST_HOUSE_VIEW = [
    {"dimension": "AssetClass", "category": "Shares", "stance": "overweight", "rationale": "r1"},
    {"dimension": "AssetClass", "category": "Bonds", "stance": "underweight", "rationale": "r2"},
    {"dimension": "AssetClass", "category": "Real estate", "stance": "neutral", "rationale": "r3"},
    {"dimension": "AssetClass", "category": "Liquidity", "stance": "overweight", "rationale": "r4"},
]

TEST_PROVIDER = StaticHouseViewProvider(TEST_HOUSE_VIEW, source="test", as_of="2026-01-01")


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
    result = compare_portfolio_to_house_view(portfolio, TEST_PROVIDER)
    shares = next(r for r in result if r["category"] == "Shares")
    assert shares["relative_position"] == "aligned"


def test_overweight_stance_with_negative_deviation_is_opposite():
    portfolio = _portfolio(shares_dev=-0.05, bonds_dev=0.0)
    result = compare_portfolio_to_house_view(portfolio, TEST_PROVIDER)
    shares = next(r for r in result if r["category"] == "Shares")
    assert shares["relative_position"] == "opposite"


def test_underweight_stance_with_negative_deviation_is_aligned():
    portfolio = _portfolio(shares_dev=0.0, bonds_dev=-0.03)
    result = compare_portfolio_to_house_view(portfolio, TEST_PROVIDER)
    bonds = next(r for r in result if r["category"] == "Bonds")
    assert bonds["relative_position"] == "aligned"


def test_underweight_stance_with_positive_deviation_is_opposite():
    portfolio = _portfolio(shares_dev=0.0, bonds_dev=0.03)
    result = compare_portfolio_to_house_view(portfolio, TEST_PROVIDER)
    bonds = next(r for r in result if r["category"] == "Bonds")
    assert bonds["relative_position"] == "opposite"


def test_neutral_stance_is_not_applicable():
    portfolio = _portfolio(shares_dev=0.0, bonds_dev=0.0)
    result = compare_portfolio_to_house_view(portfolio, TEST_PROVIDER)
    real_estate = next(r for r in result if r["category"] == "Real estate")
    assert real_estate["relative_position"] == "not_applicable"


def test_category_with_no_matching_saa_row_is_skipped():
    portfolio = _portfolio(shares_dev=0.0, bonds_dev=0.0)
    result = compare_portfolio_to_house_view(portfolio, TEST_PROVIDER)
    categories = [r["category"] for r in result]
    assert "Liquidity" not in categories  # no SAA row for it in this portfolio


def test_empty_portfolio_returns_empty_list():
    result = compare_portfolio_to_house_view({}, TEST_PROVIDER)
    assert result == []


def test_exact_zero_deviation_is_at_target_not_opposite_for_underweight():
    # Real bug found via a live client (Spock): actual=0.0%, target=0.0%
    # for an "underweight" house view category incorrectly came back as
    # "overexposed" — deviation is exactly 0, which strict "< 0" excludes.
    # Being exactly at target is now its own explicit state, distinct
    # from both "aligned" and "opposite".
    portfolio = _portfolio(shares_dev=0.0, bonds_dev=0.0)
    result = compare_portfolio_to_house_view(portfolio, TEST_PROVIDER)
    bonds = next(r for r in result if r["category"] == "Bonds")
    assert bonds["relative_position"] == "at_target"


def test_exact_zero_deviation_is_at_target_not_aligned_for_overweight():
    # Symmetric case for "overweight" stance: being exactly at the
    # client's own SAA target must not be narrated as if the client had
    # actually acted on the bank's tactical overweight call.
    portfolio = _portfolio(shares_dev=0.0, bonds_dev=0.0)
    result = compare_portfolio_to_house_view(portfolio, TEST_PROVIDER)
    shares = next(r for r in result if r["category"] == "Shares")
    assert shares["relative_position"] == "at_target"


def test_every_row_carries_as_of_source_and_is_mock():
    portfolio = _portfolio(shares_dev=0.05, bonds_dev=0.0)
    result = compare_portfolio_to_house_view(portfolio, TEST_PROVIDER)
    shares = next(r for r in result if r["category"] == "Shares")
    assert shares["as_of"] == "2026-01-01"
    assert shares["source"] == "test"
    assert shares["is_mock"] is False


def test_mock_provider_tags_rows_as_mock():
    provider = MockHouseViewProvider()
    rows = provider.get_house_view()
    assert all(row["is_mock"] is True for row in rows)
    assert all(row["source"] == "mock" for row in rows)


def test_get_house_view_defaults_to_mock_provider():
    rows = get_house_view()
    assert rows
    assert all(row["is_mock"] is True for row in rows)


def test_compare_defaults_to_mock_provider_when_none_given():
    portfolio = {
        "saa_deviations": {
            "AssetClass": [{"category": "Shares", "actual": 0.55, "target": 0.5, "deviation_from_target": 0.05}]
        }
    }
    result = compare_portfolio_to_house_view(portfolio)
    shares = next(r for r in result if r["category"] == "Shares")
    assert shares["is_mock"] is True


def test_precedence_note_is_a_real_sentence_not_empty():
    # Guards against the precedence rule silently regressing to an empty
    # or placeholder string — this is the exact text prompt_builder.py
    # surfaces to the model.
    assert len(HOUSE_VIEW_PRECEDENCE_NOTE) > 20
    assert "precedence" in HOUSE_VIEW_PRECEDENCE_NOTE.lower() or "override" in HOUSE_VIEW_PRECEDENCE_NOTE.lower()
