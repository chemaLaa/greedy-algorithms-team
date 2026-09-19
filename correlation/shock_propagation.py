"""
correlation/shock_propagation.py
─────────────────────────────────
Single-factor shock approximation.

IMPORTANT: This is a LINEAR, SINGLE-FACTOR approximation only.
It multiplies the portfolio's look-through exposure to a factor's associated
SAA category by the shock size and the total portfolio value. This is NOT
a multi-factor risk model, does NOT account for correlations between factors,
and does NOT produce a reliable point estimate of actual P&L impact. Use it
only to convey order-of-magnitude sensitivity to the advisor, with this
caveat stated explicitly in any output.
"""
from __future__ import annotations

from typing import Optional

FACTORS = ["rates", "usd", "tech", "health_care", "energy", "em"]

# Maps each factor to its SAA Industry or CurrencyGroup category name
# (these must match the actual category strings in reference.json)
FACTOR_TO_SAA_CATEGORY = {
    "rates":       ("AssetClass",    "Bonds"),
    "usd":         ("CurrencyGroup", "US-Dollar"),
    "tech":        ("Industry",      "Information Technology"),
    "health_care": ("Industry",      "Health Care"),
    "energy":      ("Industry",      "Energy"),
    "em":          ("CountryGroup",  "Emerging Markets"),
}

SHOCK_SIZE_BY_FACTOR = {
    "rates":       -0.10,
    "usd":         -0.08,
    "tech":        -0.20,
    "health_care": -0.15,
    "energy":      -0.25,
    "em":          -0.18,
}


def apply_factor_shock(
    portfolio_view: dict,       # one portfolio dict from build_client_view()
    priority_bundle: dict,      # the analysis_layer bundle for this portfolio
    factor: str,
    shock_pct: float,
) -> dict:
    """
    Compute the estimated CHF impact of a single-factor shock on this
    portfolio, using the portfolio's current look-through exposure to the
    factor's SAA category.

    Returns a dict with the factor, shock_pct, exposure, chf_impact,
    baseline_expected_return, baseline_source, and approximation_caveat.

    Raises ValueError if `factor` is not in FACTORS.
    """
    if factor not in FACTORS:
        raise ValueError(
            f"Unknown factor {factor!r}. Must be one of: {FACTORS}"
        )

    dimension, category = FACTOR_TO_SAA_CATEGORY[factor]

    portfolio_value: Optional[float] = portfolio_view.get(
        "AssetsUnderManagementInDefaultCurrency"
    )

    # Find exposure from saa_target_deviations
    exposure: float = 0.0
    for d in priority_bundle.get("saa_target_deviations") or []:
        if d.get("dimension") == dimension and d.get("category") == category:
            actual = d.get("actual")
            if actual is not None:
                exposure = float(actual)
            break

    if portfolio_value is not None:
        chf_impact: Optional[float] = exposure * shock_pct * float(portfolio_value)
    else:
        chf_impact = None

    # Baseline expected return from the risk/return snapshot
    baseline_expected_return: Optional[float] = None
    risk_return = priority_bundle.get("current_risk_return") or {}
    if risk_return.get("status") == "ok":
        er = risk_return.get("expected_return")
        if er is not None:
            baseline_expected_return = float(er)

    return {
        "factor": factor,
        "shock_pct": shock_pct,
        "exposure": exposure,
        "chf_impact": chf_impact,
        "baseline_expected_return": baseline_expected_return,
        "baseline_source": (
            "bank_expected_return_engine"
            if baseline_expected_return is not None
            else "unavailable"
        ),
        "approximation_caveat": (
            "Linear single-factor approximation only. "
            "Does not account for factor correlations or non-linear exposures."
        ),
    }
