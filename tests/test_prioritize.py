from analysis_layer.prioritize import build_portfolio_priorities


def portfolio():
    return {
        "PortfolioId": 1,
        "Name": "P",
        "AssetsUnderManagementInDefaultCurrency": 1000.0,
        "LiquidityInDefaultCurrency": 150.0,
        "Volatility": 0.10,
        "ExpectedReturn": 0.04,
        "ValueAtRisk": 0.08,
        "PerformanceHistory": [
            {"Date": "2026-06-01", "Value": 100.0},
            {"Date": "2026-07-01", "Value": 105.0},
        ],
        "SecurityPositions": [
            {
                "SecurityId": 10,
                "SecurityName": "Big Position",
                "PortfolioValuePercentage": 0.30,
                "ContributionVolatility": 0.07,
            },
            {
                "SecurityId": 11,
                "SecurityName": "Other",
                "PortfolioValuePercentage": 0.55,
                "ContributionVolatility": 0.03,
            },
        ],
        "AccountPositions": [{"AccountName": "Cash", "PortfolioValuePercentage": 0.15, "ContributionVolatility": 0.0}],
        "saa_deviations": {
            "AssetClass": [
                {
                    "category": "Shares",
                    "actual": 0.70,
                    "target": 0.55,
                    "min": 0.40,
                    "max": 0.65,
                    "breaches_min": False,
                    "breaches_max": True,
                }
            ],
            "Industry": [{"category": "Technology", "actual": 0.25, "target": 0.15}],
        },
    }


def test_priorities_are_structured_and_self_contained():
    p = portfolio()
    client = {
        "active_violations": [
            {"PortfolioId": 1, "Severity": "Error", "RuleCode": "RULE_X", "RuleDescription": "Important violation"}
        ],
        "notes": [{"CreatedByDateUTC": "2026-06-15T00:00:00Z"}],
    }
    result = build_portfolio_priorities(client, p, ref=None)
    assert result["priorities"][0]["type"] == "violation"
    saa = next(x for x in result["priorities"] if x["type"] == "saa_breach")
    assert saa["actual"] == 0.70
    assert saa["target"] == 0.55
    assert saa["max"] == 0.65
    assert round(saa["breach_amount_pp"], 6) == 5.0
    assert any(x["type"] == "high_liquidity" for x in result["priorities"])
    assert result["saa_target_deviations"][0]["category"] in {"Shares", "Technology"}


def test_target_only_saa_is_not_called_a_breach():
    p = portfolio()
    p["saa_deviations"] = {"Industry": [{"category": "Technology", "actual": 0.40, "target": 0.10}]}
    client = {"active_violations": [], "notes": []}
    result = build_portfolio_priorities(client, p, ref=None)
    assert not any(x["type"] == "saa_breach" for x in result["priorities"])
    assert result["saa_target_deviations"][0]["deviation_from_target_pp"] == 30.000000000000004


def test_client_tags_pass_through_from_client_view():
    p = portfolio()
    client = {
        "active_violations": [],
        "notes": [],
        "tags": [
            {"TagName": "Switzerland", "TagTypeName": "Region", "Scope": "Client"},
            {"TagName": "Health Care", "TagTypeName": "Industry", "Scope": "Client"},
        ],
    }
    result = build_portfolio_priorities(client, p, ref=None)
    assert result["client_tags"] == client["tags"]


def test_client_tags_defaults_to_empty_list_when_absent():
    p = portfolio()
    client = {"active_violations": [], "notes": []}
    result = build_portfolio_priorities(client, p, ref=None)
    assert result["client_tags"] == []
