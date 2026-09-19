"""Build deterministic, structured attention facts for a client briefing.

The result deliberately separates hard facts from LLM narrative. Scores are
heuristics for ordering, not financial recommendations.
"""
from __future__ import annotations

import math
from typing import Any, TYPE_CHECKING

from .concentration import concentration_snapshot, largest_single_positions
from .material_changes import change_since_last_interaction, resolve_interaction_date
from .performance import current_risk_return_snapshot, performance_trend, risk_contributor_analysis
from .validation import validate_liquidity, validate_portfolio_analysis_inputs

if TYPE_CHECKING:
    from data_layer.reference_index import ReferenceIndex

SEVERITY_BASE = {"Error": 100.0, "Warning": 75.0}

# Existing supplementary heuristic. Authoritative MAX_SINGLE_POSITION rules,
# when present, still take precedence via active suitability violations.
SINGLE_POSITION_CONCENTRATION_THRESHOLD = 0.20

# The supplied URO advisor-dashboard screenshot includes a built-in
# "Liquidity > 10%" attention filter. Keep it configurable rather than hidden.
LIQUIDITY_ATTENTION_THRESHOLD = 0.10


def _finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _fact_id(portfolio_id: Any, kind: str, suffix: Any) -> str:
    return f"{portfolio_id}:{kind}:{suffix}"


def _saa_target_deviations(portfolio: dict, n: int = 5) -> list[dict]:
    rows_out: list[dict] = []
    for dimension, rows in (portfolio.get("saa_deviations") or {}).items():
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            actual, target = row.get("actual"), row.get("target")
            if not (_finite(actual) and _finite(target)):
                continue
            deviation = float(actual) - float(target)
            rows_out.append({
                "dimension": dimension,
                "category": row.get("category"),
                "actual": float(actual),
                "target": float(target),
                "deviation_from_target": deviation,
                "deviation_from_target_pp": 100.0 * deviation,
            })
    rows_out.sort(key=lambda x: abs(x["deviation_from_target"]), reverse=True)
    return rows_out[:n]


def build_portfolio_priorities(
    client_view: dict,
    portfolio: dict,
    ref: "ReferenceIndex | None" = None,
) -> dict:
    portfolio_id = portfolio.get("PortfolioId")
    priorities: list[dict] = []
    quality = validate_portfolio_analysis_inputs(portfolio)

    # 1) Authoritative suitability / rule violations.
    for i, violation in enumerate(client_view.get("active_violations") or []):
        if violation.get("PortfolioId") != portfolio_id:
            continue
        severity = violation.get("Severity")
        description = violation.get("RuleDescription") or violation.get("RuleCode")
        priorities.append({
            "fact_id": _fact_id(portfolio_id, "violation", violation.get("RuleCode") or i),
            "type": "violation",
            "severity": severity,
            "priority_score": SEVERITY_BASE.get(severity, 60.0),
            "description": description,
            "rule_code": violation.get("RuleCode"),
            "source": "SuitabilityViolations",
        })

    # 2) SAA bound breaches only when a real bound exists.
    for dimension, rows in (portfolio.get("saa_deviations") or {}).items():
        for i, row in enumerate(rows or []):
            if not isinstance(row, dict):
                continue
            actual = row.get("actual")
            target = row.get("target")
            min_v = row.get("min", row.get("MinPercentage"))
            max_v = row.get("max", row.get("MaxPercentage"))
            breaches_min = bool(row.get("breaches_min")) if _finite(min_v) else False
            breaches_max = bool(row.get("breaches_max")) if _finite(max_v) else False
            if not (breaches_min or breaches_max):
                continue

            breach = "min" if breaches_min else "max"
            boundary = float(min_v if breaches_min else max_v)
            actual_f = float(actual) if _finite(actual) else None
            breach_amount = abs(actual_f - boundary) if actual_f is not None else None
            score = 78.0 + min(20.0, 100.0 * breach_amount) if breach_amount is not None else 78.0
            priorities.append({
                "fact_id": _fact_id(portfolio_id, "saa_breach", f"{dimension}:{row.get('category')}:{i}"),
                "type": "saa_breach",
                "severity": "Warning",
                "priority_score": score,
                "dimension": dimension,
                "category": row.get("category"),
                "actual": actual_f,
                "target": float(target) if _finite(target) else None,
                "min": float(min_v) if _finite(min_v) else None,
                "max": float(max_v) if _finite(max_v) else None,
                "breach": breach,
                "breach_amount": breach_amount,
                "breach_amount_pp": 100.0 * breach_amount if breach_amount is not None else None,
                "source": "StrategicAssetAllocation",
            })

    # 3) Large security line as a supplementary concentration heuristic.
    top_position = largest_single_positions(portfolio, n=1)
    if top_position and top_position[0]["absolute_weight"] > SINGLE_POSITION_CONCENTRATION_THRESHOLD:
        excess = top_position[0]["absolute_weight"] - SINGLE_POSITION_CONCENTRATION_THRESHOLD
        priorities.append({
            "fact_id": _fact_id(portfolio_id, "single_position_concentration", top_position[0].get("SecurityId")),
            "type": "single_position_concentration",
            "severity": "Warning",
            "priority_score": 55.0 + min(15.0, 100.0 * excess),
            "security_id": top_position[0].get("SecurityId"),
            "security_name": top_position[0].get("SecurityName"),
            "weight": top_position[0]["PortfolioValuePercentage"],
            "threshold": SINGLE_POSITION_CONCENTRATION_THRESHOLD,
            "source": "analysis_heuristic",
        })

    # 4) URO's own dashboard has a "Liquidity > 10%" attention filter.
    liquidity = validate_liquidity(portfolio)
    ratio = liquidity.get("liquidity_ratio")
    if _finite(ratio) and float(ratio) > LIQUIDITY_ATTENTION_THRESHOLD:
        priorities.append({
            "fact_id": _fact_id(portfolio_id, "liquidity", "above_10pct"),
            "type": "high_liquidity",
            "severity": "Info",
            "priority_score": 40.0 + min(20.0, 100.0 * (float(ratio) - LIQUIDITY_ATTENTION_THRESHOLD)),
            "liquidity_ratio": float(ratio),
            "threshold": LIQUIDITY_ATTENTION_THRESHOLD,
            "liquidity": liquidity.get("liquidity"),
            "aum": liquidity.get("aum"),
            "source": "uro_ui_attention_filter",
        })

    priorities.sort(key=lambda p: (-p["priority_score"], p["type"]))

    # Fallback material-change comparison. A persisted state diff should replace
    # this when available.
    interaction = resolve_interaction_date(client_view)
    since = interaction["date"]

    risk_analysis = risk_contributor_analysis(portfolio, n=3)

    return {
        "portfolio_id": portfolio_id,
        "portfolio_name": portfolio.get("Name"),
        "quality": quality,
        "priorities": priorities,
        "performance": performance_trend(portfolio),
        "current_risk_return": current_risk_return_snapshot(portfolio),
        "risk_attribution": risk_analysis,
        # Backward compatibility with previous bundle shape:
        "top_risk_contributors": risk_analysis["contributors"],
        "change_since_last_interaction": change_since_last_interaction(
            portfolio,
            since,
            source=interaction.get("source") or "unavailable",
            approximation=bool(interaction.get("approximation")),
        ),
        "saa_target_deviations": _saa_target_deviations(portfolio, n=5),
        "concentrations": concentration_snapshot(portfolio, ref=ref),
        "liquidity": liquidity,
    }


def build_client_priorities(client_view: dict, ref: "ReferenceIndex | None" = None) -> list[dict]:
    """Run deterministic analysis for every portfolio belonging to a client."""
    portfolios = client_view.get("portfolios")
    if portfolios is None:
        portfolios = client_view.get("Portfolios") or []
    return [build_portfolio_priorities(client_view, portfolio, ref=ref) for portfolio in portfolios]
