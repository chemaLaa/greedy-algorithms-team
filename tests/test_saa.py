from helpers import first_client
from data_layer.saa import actual_exposure, saa_targets, saa_deviations


def _portfolio():
    client, ref = first_client()
    return client["Portfolios"][0], ref


def _approx(a, b, tol=1e-6):
    return abs(a - b) < tol


def test_actual_exposure_combines_direct_and_fund_positions():
    portfolio, ref = _portfolio()
    exposure = actual_exposure(portfolio, "AssetClass", ref)

    # Nestle (direct, 35% of portfolio, SAA_AssetClassName "Shares")
    # + the fund's Shares slice (25% * 60% = 15%) = 50% Shares total.
    assert _approx(exposure["Shares"], 0.50)
    # The fund's Bonds slice: 25% * 40% = 10%.
    assert _approx(exposure["Bonds"], 0.10)


def test_saa_targets_reads_min_target_max():
    portfolio, ref = _portfolio()
    targets = saa_targets(portfolio, "AssetClass", ref)
    assert targets["Shares"] == {"min": 0.40, "target": 0.50, "max": 0.60}
    assert targets["Bonds"] == {"min": 0.30, "target": 0.40, "max": 0.50}


def test_saa_deviations_flags_breach_below_min():
    portfolio, ref = _portfolio()
    rows = {r["category"]: r for r in saa_deviations(portfolio, "AssetClass", ref)}

    # Shares: actual 0.50 vs target 0.50 -> on target, no breach.
    assert _approx(rows["Shares"]["deviation_from_target"], 0.0)
    assert rows["Shares"]["breaches_min"] is False
    assert rows["Shares"]["breaches_max"] is False

    # Bonds: actual 0.10 vs min 0.30 -> underweight, breaches min.
    assert rows["Bonds"]["breaches_min"] is True
    assert _approx(rows["Bonds"]["deviation_from_target"], 0.10 - 0.40)


def test_saa_deviations_includes_categories_with_zero_actual_and_target():
    portfolio, ref = _portfolio()
    rows = {r["category"]: r for r in saa_deviations(portfolio, "AssetClass", ref)}
    # Fixture defines a "Mixed" SAA target of 0.0 with no actual holding
    # in that bucket — the row should still surface (not be silently
    # dropped for being all-zero) so an advisor can see "on target at 0%"
    # rather than the category vanishing entirely.
    assert "Mixed" in rows
    assert rows["Mixed"]["target"] == 0.0
    assert rows["Mixed"]["actual"] == 0.0
    assert rows["Mixed"]["breaches_min"] is False
    assert rows["Mixed"]["breaches_max"] is False
