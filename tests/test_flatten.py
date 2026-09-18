from helpers import first_client
from data_layer import build_client_view


def test_build_client_view_has_expected_shape():
    client, ref = first_client()
    view = build_client_view(client, ref)

    expected_keys = {
        "client_ref", "client_id", "display_name", "reporting_currency",
        "risk_profile", "esg_profile", "aum", "liquidity", "tags", "notes",
        "portfolios", "proposals", "transactions", "active_violations", "raw",
    }
    assert expected_keys.issubset(view.keys())
    assert view["client_ref"] == "CASE-001"
    assert view["display_name"] == "Anna Meier"


def test_build_client_view_resolves_risk_profile():
    client, ref = first_client()
    view = build_client_view(client, ref)
    assert view["risk_profile"]["Name"] == "Balanced"


def test_portfolio_positions_are_resolved():
    client, ref = first_client()
    view = build_client_view(client, ref)
    portfolio = view["portfolios"][0]

    positions_by_name = {
        p["SecurityName"]: p for p in portfolio["resolved_security_positions"]
    }
    nestle = positions_by_name["Nestle SA"]
    assert nestle["security"] is not None
    assert nestle["security"]["Name"] == "Nestle SA"
    assert nestle["is_recommended"] is True

    fund = positions_by_name["Global Balanced Fund"]
    assert fund["security"]["IsUnbundlingEnabled"] is True
    assert fund["is_recommended"] is False


def test_portfolio_has_saa_deviations_for_all_four_dimensions():
    client, ref = first_client()
    view = build_client_view(client, ref)
    portfolio = view["portfolios"][0]
    assert set(portfolio["saa_deviations"].keys()) == {
        "AssetClass", "CurrencyGroup", "CountryGroup", "Industry"
    }


def test_display_name_falls_back_to_client_ref_for_companies_without_name():
    _, ref = first_client()
    company_client = {
        "ClientRef": "CASE-999",
        "IsClientACompany": True,
        # no "Company" field — should fall back gracefully
    }
    from data_layer.flatten import _display_name
    assert _display_name(company_client) == "CASE-999"
