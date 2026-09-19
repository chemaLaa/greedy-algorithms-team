"""
Tests for correlation/shock_propagation.py:
  - Known portfolio value + exposure → correct chf_impact
  - Unknown factor → ValueError
  - portfolio_value = None → chf_impact = None
  - current_risk_return status != "ok" → baseline_expected_return = None
  - No matching SAA entry → exposure = 0.0, chf_impact = 0.0
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import math
import pytest

from correlation.shock_propagation import (
    FACTORS,
    FACTOR_TO_SAA_CATEGORY,
    SHOCK_SIZE_BY_FACTOR,
    apply_factor_shock,
)


def _make_portfolio(value=1_000_000):
    return {"AssetsUnderManagementInDefaultCurrency": value}


def _make_bundle(exposure_dimension, exposure_category, exposure_weight, risk_return_status="ok", expected_return=0.05):
    saa_entry = {
        "dimension": exposure_dimension,
        "category": exposure_category,
        "actual": exposure_weight,
        "target": 0.30,
        "deviation_from_target_pp": (exposure_weight - 0.30) * 100,
    }
    return {
        "saa_target_deviations": [saa_entry],
        "current_risk_return": {
            "status": risk_return_status,
            "expected_return": expected_return,
            "volatility": 0.08,
        },
    }


# ---------------------------------------------------------------------------
# Correct chf_impact calculation
# ---------------------------------------------------------------------------

def test_chf_impact_computed_correctly():
    portfolio = _make_portfolio(value=2_000_000)
    # tech factor: dimension=Industry, category=Information Technology
    dimension, category = FACTOR_TO_SAA_CATEGORY["tech"]
    bundle = _make_bundle(dimension, category, exposure_weight=0.25)

    result = apply_factor_shock(portfolio, bundle, "tech", shock_pct=-0.20)

    expected_impact = 0.25 * (-0.20) * 2_000_000
    assert math.isclose(result["chf_impact"], expected_impact, rel_tol=1e-9)
    assert result["exposure"] == 0.25
    assert result["factor"] == "tech"
    assert result["shock_pct"] == -0.20


def test_chf_impact_uses_default_shock_size():
    portfolio = _make_portfolio(value=1_000_000)
    dimension, category = FACTOR_TO_SAA_CATEGORY["energy"]
    bundle = _make_bundle(dimension, category, exposure_weight=0.15)

    result = apply_factor_shock(portfolio, bundle, "energy", SHOCK_SIZE_BY_FACTOR["energy"])

    expected_impact = 0.15 * SHOCK_SIZE_BY_FACTOR["energy"] * 1_000_000
    assert math.isclose(result["chf_impact"], expected_impact, rel_tol=1e-9)


# ---------------------------------------------------------------------------
# Unknown factor → ValueError
# ---------------------------------------------------------------------------

def test_unknown_factor_raises_value_error():
    portfolio = _make_portfolio()
    bundle = {"saa_target_deviations": [], "current_risk_return": {"status": "ok"}}

    with pytest.raises(ValueError, match="Unknown factor"):
        apply_factor_shock(portfolio, bundle, "bad_factor", -0.10)


def test_all_defined_factors_do_not_raise():
    portfolio = _make_portfolio()
    bundle = {"saa_target_deviations": [], "current_risk_return": {"status": "ok"}}

    for factor in FACTORS:
        result = apply_factor_shock(portfolio, bundle, factor, SHOCK_SIZE_BY_FACTOR[factor])
        assert result["factor"] == factor


# ---------------------------------------------------------------------------
# portfolio_value = None → chf_impact = None
# ---------------------------------------------------------------------------

def test_chf_impact_is_none_when_portfolio_value_is_none():
    portfolio = {"AssetsUnderManagementInDefaultCurrency": None}
    dimension, category = FACTOR_TO_SAA_CATEGORY["rates"]
    bundle = _make_bundle(dimension, category, exposure_weight=0.40)

    result = apply_factor_shock(portfolio, bundle, "rates", SHOCK_SIZE_BY_FACTOR["rates"])

    assert result["chf_impact"] is None


def test_chf_impact_is_none_when_portfolio_value_key_missing():
    portfolio = {}
    bundle = {"saa_target_deviations": [], "current_risk_return": {"status": "ok"}}

    result = apply_factor_shock(portfolio, bundle, "usd", -0.08)

    assert result["chf_impact"] is None


# ---------------------------------------------------------------------------
# current_risk_return status != "ok" → baseline_expected_return = None
# ---------------------------------------------------------------------------

def test_baseline_expected_return_none_when_status_unavailable():
    portfolio = _make_portfolio()
    dimension, category = FACTOR_TO_SAA_CATEGORY["em"]
    bundle = _make_bundle(dimension, category, 0.10, risk_return_status="unavailable", expected_return=0.06)

    result = apply_factor_shock(portfolio, bundle, "em", SHOCK_SIZE_BY_FACTOR["em"])

    assert result["baseline_expected_return"] is None
    assert result["baseline_source"] == "unavailable"


def test_baseline_expected_return_none_when_status_invalid():
    portfolio = _make_portfolio()
    bundle = {
        "saa_target_deviations": [],
        "current_risk_return": {"status": "invalid", "expected_return": 0.04},
    }

    result = apply_factor_shock(portfolio, bundle, "tech", -0.20)

    assert result["baseline_expected_return"] is None


def test_baseline_expected_return_populated_when_status_ok():
    portfolio = _make_portfolio()
    dimension, category = FACTOR_TO_SAA_CATEGORY["health_care"]
    bundle = _make_bundle(dimension, category, 0.12, risk_return_status="ok", expected_return=0.055)

    result = apply_factor_shock(portfolio, bundle, "health_care", SHOCK_SIZE_BY_FACTOR["health_care"])

    assert math.isclose(result["baseline_expected_return"], 0.055, rel_tol=1e-9)
    assert result["baseline_source"] == "bank_expected_return_engine"


# ---------------------------------------------------------------------------
# No matching SAA entry → exposure = 0.0, chf_impact = 0.0
# ---------------------------------------------------------------------------

def test_no_matching_saa_entry_exposure_zero():
    portfolio = _make_portfolio(value=500_000)
    bundle = {
        "saa_target_deviations": [
            {"dimension": "AssetClass", "category": "Shares", "actual": 0.50},
        ],
        "current_risk_return": {"status": "ok", "expected_return": 0.04},
    }

    result = apply_factor_shock(portfolio, bundle, "tech", -0.20)

    assert result["exposure"] == 0.0
    assert result["chf_impact"] == 0.0


def test_no_saa_deviations_key_exposure_zero():
    portfolio = _make_portfolio(value=1_000_000)
    bundle = {"current_risk_return": {"status": "ok", "expected_return": 0.03}}

    result = apply_factor_shock(portfolio, bundle, "energy", -0.25)

    assert result["exposure"] == 0.0
    assert result["chf_impact"] == 0.0


# ---------------------------------------------------------------------------
# Approximation caveat always present
# ---------------------------------------------------------------------------

def test_approximation_caveat_always_present():
    portfolio = _make_portfolio()
    bundle = {"saa_target_deviations": [], "current_risk_return": {"status": "ok"}}

    result = apply_factor_shock(portfolio, bundle, "rates", -0.10)

    assert "Linear single-factor approximation" in result["approximation_caveat"]
    assert "factor correlations" in result["approximation_caveat"]
