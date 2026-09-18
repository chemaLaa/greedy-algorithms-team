from helpers import first_client
from data_layer import build_client_view
from analysis_layer import build_client_priorities
from state.snapshot import build_portfolio_snapshot


def _bundle():
    client, ref = first_client()
    view = build_client_view(client, ref)
    bundles = build_client_priorities(view, ref)
    return view["portfolios"][0], bundles[0]


def test_snapshot_captures_portfolio_value():
    portfolio, bundle = _bundle()
    snapshot = build_portfolio_snapshot(portfolio, bundle)
    assert snapshot["portfolio_value"] == portfolio["AssetsUnderManagementInDefaultCurrency"]


def test_snapshot_allocation_matches_saa_deviations():
    portfolio, bundle = _bundle()
    snapshot = build_portfolio_snapshot(portfolio, bundle)
    assert snapshot["allocation"]["AssetClass"]["Shares"] == 0.5
    assert snapshot["allocation"]["AssetClass"]["Bonds"] == 0.1


def test_snapshot_violations_match_active_violations():
    portfolio, bundle = _bundle()
    snapshot = build_portfolio_snapshot(portfolio, bundle)
    # Fixture: only MAX_SINGLE_POSITION survives override filtering.
    assert snapshot["violations"] == ["MAX_SINGLE_POSITION"]


def test_snapshot_top_positions_sorted_by_weight():
    portfolio, bundle = _bundle()
    snapshot = build_portfolio_snapshot(portfolio, bundle)
    assert snapshot["top_positions"][0]["SecurityName"] == "Nestle SA"


def test_snapshot_has_a_timestamp():
    portfolio, bundle = _bundle()
    snapshot = build_portfolio_snapshot(portfolio, bundle)
    assert snapshot["captured_at"]  # non-empty ISO string
