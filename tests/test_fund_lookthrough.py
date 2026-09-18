from helpers import load_fixture_data
from data_layer.fund_lookthrough import fund_breakdown, is_look_through_eligible


def test_is_look_through_eligible():
    _, _, ref = load_fixture_data()
    assert is_look_through_eligible(2002, ref) is True   # fund, IsUnbundlingEnabled=true
    assert is_look_through_eligible(1001, ref) is False  # plain stock


def test_fund_breakdown_translates_and_normalizes_weight():
    _, _, ref = load_fixture_data()
    breakdown = fund_breakdown(2002, "AssetClass", ref)
    breakdown_dict = dict(breakdown)

    # Fixture: FundUnbundlingMappings for fund 2002 are
    # "Equities Switzerland" (Weight 60.0) and "Bonds CHF domestic"
    # (Weight 40.0) — both plain names, translated here to the SAA
    # categories the securities table pairs them with ("Shares"/"Bonds"),
    # and the weight converted from percentage points to a 0-1 fraction.
    assert breakdown_dict["Shares"] == 0.6
    assert breakdown_dict["Bonds"] == 0.4


def test_fund_breakdown_empty_for_non_fund():
    _, _, ref = load_fixture_data()
    assert fund_breakdown(1001, "AssetClass", ref) == []


def test_fund_breakdown_empty_for_unknown_security():
    _, _, ref = load_fixture_data()
    assert fund_breakdown(999999, "AssetClass", ref) == []
