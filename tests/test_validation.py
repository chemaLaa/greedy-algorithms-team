from analysis_layer.validation import (
    audit_reference_data,
    validate_current_portfolio_metrics,
    validate_interaction_proxy,
    validate_liquidity,
    validate_performance_history,
    validate_portfolio_weights,
    validate_risk_contributions,
    validate_saa_deviations,
)


def base_portfolio():
    return {
        "PortfolioId": 1,
        "Name": "Test",
        "AssetsUnderManagementInDefaultCurrency": 1000.0,
        "LiquidityInDefaultCurrency": 100.0,
        "Volatility": 0.10,
        "ExpectedReturn": 0.04,
        "ValueAtRisk": 0.08,
        "PerformanceHistory": [
            {"Date": "2026-06-01", "Value": 100.0},
            {"Date": "2026-07-01", "Value": 101.0},
        ],
        "SecurityPositions": [
            {"SecurityId": 10, "PortfolioValuePercentage": 0.70, "ContributionVolatility": 0.08}
        ],
        "AccountPositions": [
            {"AccountName": "cash", "PortfolioValuePercentage": 0.30, "ContributionVolatility": 0.02}
        ],
        "saa_deviations": {
            "AssetClass": [
                {
                    "category": "Shares",
                    "actual": 0.60,
                    "target": 0.55,
                    "min": 0.40,
                    "max": 0.65,
                    "breaches_min": False,
                    "breaches_max": False,
                }
            ]
        },
    }


def test_performance_history_ok_and_semantics_unconfirmed():
    result = validate_performance_history(base_portfolio())
    assert result["status"] == "ok"
    assert result["chronologically_sorted"] is True
    assert result["return_semantics_confirmed"] is False
    assert result["performance_ytd_field"] == "absent"


def test_unsorted_history_is_partial_not_crash():
    p = base_portfolio()
    p["PerformanceHistory"] = list(reversed(p["PerformanceHistory"]))
    result = validate_performance_history(p)
    assert result["status"] == "partial"
    assert "history_not_chronologically_sorted" in result["reasons"]


def test_duplicate_history_date_is_invalid():
    p = base_portfolio()
    p["PerformanceHistory"].append({"Date": "2026-07-01", "Value": 99.0})
    assert validate_performance_history(p)["status"] == "invalid"


def test_optional_provided_performance_ytd_is_detected_but_not_calculated():
    p = base_portfolio()
    p["PerformanceYTD"] = 0.123
    result = validate_performance_history(p)
    assert result["performance_ytd_field"] == "provided"


def test_current_metrics_allow_missing_expected_return():
    p = base_portfolio()
    p.pop("ExpectedReturn")
    result = validate_current_portfolio_metrics(p)
    assert result["status"] == "partial"
    assert result["volatility"] == 0.10
    assert result["expected_return"] is None


def test_liquidity_ratio():
    result = validate_liquidity(base_portfolio())
    assert result["status"] == "ok"
    assert abs(result["liquidity_ratio"] - 0.10) < 1e-12


def test_weights_include_accounts_and_allow_rounding():
    p = base_portfolio()
    p["SecurityPositions"][0]["PortfolioValuePercentage"] = 0.699
    p["AccountPositions"][0]["PortfolioValuePercentage"] = 0.2992
    result = validate_portfolio_weights(p)
    assert result["status"] == "ok"
    assert result["reconciles"] is True


def test_negative_weight_reported_but_not_rejected():
    p = base_portfolio()
    p["SecurityPositions"] = [{"PortfolioValuePercentage": 1.10}, {"PortfolioValuePercentage": -0.10}]
    p["AccountPositions"] = []
    result = validate_portfolio_weights(p)
    assert result["status"] == "ok"
    assert result["negative_weight_count"] == 1


def test_risk_includes_security_and_account_positions():
    result = validate_risk_contributions(base_portfolio())
    assert result["status"] == "ok"
    assert result["security_contribution_count"] == 1
    assert result["account_contribution_count"] == 1


def test_negative_risk_contribution_can_be_valid():
    p = base_portfolio()
    p["SecurityPositions"] = [
        {"ContributionVolatility": 0.13, "PortfolioValuePercentage": 0.70},
        {"ContributionVolatility": -0.05, "PortfolioValuePercentage": 0.20},
    ]
    p["AccountPositions"] = [{"ContributionVolatility": 0.02, "PortfolioValuePercentage": 0.10}]
    result = validate_risk_contributions(p)
    assert result["status"] == "ok"
    assert result["negative_contribution_count"] == 1


def test_positive_volatility_with_zero_attribution_is_unavailable():
    p = base_portfolio()
    for pos in p["SecurityPositions"] + p["AccountPositions"]:
        pos["ContributionVolatility"] = 0.0
    result = validate_risk_contributions(p)
    assert result["status"] == "unavailable"
    assert "risk_contributions_not_populated" in result["reasons"]


def test_corrupt_risk_attribution_is_invalid():
    p = base_portfolio()
    p["SecurityPositions"][0]["ContributionVolatility"] = 574339.3767346495
    result = validate_risk_contributions(p)
    assert result["status"] == "invalid"
    assert result["reconciles"] is False


def test_target_only_saa_supported_without_breach_capability():
    p = base_portfolio()
    p["saa_deviations"] = {"Industry": [{"category": "Technology", "actual": 0.20, "target": 0.15}]}
    dim = validate_saa_deviations(p)["dimensions"]["Industry"]
    assert dim["can_compare_to_target"] is True
    assert dim["can_detect_bound_breach"] is False


def test_interaction_proxy_after_latest_history_is_unavailable():
    p = base_portfolio()
    client = {"ClientNotes": [{"CreatedByDateUTC": "2026-09-01T10:00:00Z"}]}
    result = validate_interaction_proxy(client, p)
    assert result["status"] == "unavailable"
    assert "interaction_date_after_latest_history_point" in result["reasons"]


def test_reference_audit_accepts_percent_or_fraction_lookthrough_and_negative_rows():
    reference = {
        "Securities": [{"Id": 1}, {"Id": 2}],
        "StrategicAssetAllocations": [],
        "FundUnbundlingMappings": [
            {"FundSecurityId": 1, "Weight": 110.0},
            {"FundSecurityId": 1, "Weight": -10.0},
            {"FundSecurityId": 2, "Weight": 0.7},
            {"FundSecurityId": 2, "Weight": 0.3},
        ],
    }
    result = audit_reference_data(reference)
    assert result["fund_lookthrough"]["scale_counts"]["percent_0_100"] == 1
    assert result["fund_lookthrough"]["scale_counts"]["fraction_0_1"] == 1
    assert result["fund_lookthrough"]["negative_weight_row_count"] == 1


def test_explicit_last_consultation_is_preferred_over_note_proxy():
    p = base_portfolio()
    client = {
        "LastConsultationDateUtc": "2026-06-15T10:00:00Z",
        "ClientNotes": [{"CreatedByDateUTC": "2026-05-01T10:00:00Z"}],
    }
    result = validate_interaction_proxy(client, p)
    assert result["status"] == "ok"
    assert result["source"] == "LastConsultationDateUtc"
    assert result["approximation"] is False
