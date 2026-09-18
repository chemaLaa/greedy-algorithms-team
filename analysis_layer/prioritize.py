"""
Combines the analysis functions above with data_layer's own violations and
SAA deviations into one ranked list of "what deserves the advisor's
attention" — the deterministic answer to the case's step 3 ("Identify
what matters"). Still no narrative here: this produces structured, ranked
facts. Turning them into prose is the synthesis (LLM) layer's job, not
this one's.
"""
from __future__ import annotations

from data_layer.reference_index import ReferenceIndex

from .concentration import largest_single_positions
from .material_changes import change_since_last_interaction, last_interaction_date
from .performance import performance_trend, top_risk_contributors

SEVERITY_RANK = {"Error": 2, "Warning": 1}

# A single position above this share of the portfolio is flagged as a
# concentration concern. Not a value from the source data — the schema's
# own MAX_SINGLE_POSITION suitability rule is the authoritative check for
# this; this threshold is a supplementary, deliberately conservative
# heuristic so a large-but-compliant position still surfaces for the
# advisor's attention. Documented here, not buried as a magic number.
SINGLE_POSITION_CONCENTRATION_THRESHOLD = 0.20


def build_portfolio_priorities(client_view: dict, portfolio: dict) -> dict:
    """
    One resolved-priorities bundle for a single portfolio (already inside
    client_view["portfolios"], via data_layer.build_portfolio_view).
    """
    priorities: list[dict] = []

    for violation in client_view["active_violations"]:
        if violation.get("PortfolioId") != portfolio.get("PortfolioId"):
            continue
        severity = violation.get("Severity")
        # A small number of rule codes (e.g. "Volatility range undershot
        # (portfolio risk too low)") have an empty RuleDescription
        # everywhere in the source data — no English or native-language
        # text exists for them at all. Falling back to the RuleCode itself
        # avoids surfacing a blank description; it happens to already be
        # human-readable English for the cases observed so far, though
        # that's not guaranteed for every rule code.
        description = violation.get("RuleDescription") or violation.get("RuleCode")
        priorities.append(
            {
                "type": "violation",
                "severity": severity,
                "rank": SEVERITY_RANK.get(severity, 0),
                "description": description,
                "rule_code": violation.get("RuleCode"),
            }
        )

    for dimension, rows in portfolio.get("saa_deviations", {}).items():
        for row in rows:
            if row["breaches_min"] or row["breaches_max"]:
                priorities.append(
                    {
                        "type": "saa_deviation",
                        "severity": "Warning",
                        "rank": 1,
                        "dimension": dimension,
                        "category": row["category"],
                        "actual": row["actual"],
                        "target": row["target"],
                        "breach": "min" if row["breaches_min"] else "max",
                    }
                )

    top_position = largest_single_positions(portfolio, n=1)
    if top_position and (top_position[0]["PortfolioValuePercentage"] or 0) > SINGLE_POSITION_CONCENTRATION_THRESHOLD:
        priorities.append(
            {
                "type": "concentration",
                "severity": "Warning",
                "rank": 1,
                "security_name": top_position[0]["SecurityName"],
                "weight": top_position[0]["PortfolioValuePercentage"],
            }
        )

    priorities.sort(key=lambda p: p["rank"], reverse=True)

    since = last_interaction_date(client_view.get("notes") or [])

    return {
        "portfolio_id": portfolio.get("PortfolioId"),
        "portfolio_name": portfolio.get("Name"),
        "priorities": priorities,
        "performance": performance_trend(portfolio),
        "top_risk_contributors": top_risk_contributors(portfolio, n=3),
        "change_since_last_interaction": change_since_last_interaction(portfolio, since),
    }


def build_client_priorities(client_view: dict, ref: ReferenceIndex) -> list[dict]:
    """Runs build_portfolio_priorities() for every portfolio a client has."""
    return [
        build_portfolio_priorities(client_view, portfolio)
        for portfolio in client_view["portfolios"]
    ]
