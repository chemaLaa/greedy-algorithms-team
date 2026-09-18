"""
Builds one fully-resolved "client view" per client: portfolios with
resolved positions, SAA deviations per dimension, active suitability
violations, tags and notes — everything the analysis layer needs,
already joined and unit-normalized, so nothing downstream needs to touch
reference.json directly.

This is still just data, not narrative — no LLM calls happen here.
"""
from __future__ import annotations

from .reference_index import ReferenceIndex
from .saa import saa_deviations
from .violations import active_violations

SAA_DIMENSIONS = ["AssetClass", "CurrencyGroup", "CountryGroup", "Industry"]


def resolve_security_position(pos: dict, ref: ReferenceIndex) -> dict:
    security_id = pos.get("SecurityId")
    return {
        **pos,
        "security": ref.security(security_id),  # full Securities[] row, or None
        "is_recommended": ref.is_recommended(security_id),
    }


def build_portfolio_view(portfolio: dict, ref: ReferenceIndex) -> dict:
    resolved_positions = [
        resolve_security_position(pos, ref) for pos in portfolio.get("SecurityPositions") or []
    ]

    return {
        **portfolio,
        "resolved_security_positions": resolved_positions,
        "account_positions": portfolio.get("AccountPositions") or [],
        "saa": ref.saa(portfolio.get("StrategicAssetAllocationId")),
        "saa_deviations": {
            dim: saa_deviations(portfolio, dim, ref) for dim in SAA_DIMENSIONS
        },
    }


def build_client_view(client: dict, ref: ReferenceIndex) -> dict:
    """Top-level entry point: raw Client object + ReferenceIndex -> resolved view."""
    return {
        "client_ref": client.get("ClientRef"),
        "client_id": client.get("ClientId"),
        "display_name": _display_name(client),
        "reporting_currency": client.get("ReportingCurrency"),
        "risk_profile": ref.risk_profile(client.get("RiskProfileId")),
        "esg_profile": ref.esg_profile(client.get("EsgProfileId")),
        "aum": client.get("AssetsUnderManagementInDefaultCurrency"),
        "liquidity": client.get("LiquidityInDefaultCurrency"),
        "tags": client.get("Tags") or [],
        "notes": client.get("ClientNotes") or [],
        "portfolios": [build_portfolio_view(p, ref) for p in client.get("Portfolios") or []],
        "proposals": client.get("Proposals") or [],
        "transactions": client.get("Transactions") or [],
        "active_violations": active_violations(client, ref),
        "raw": client,  # escape hatch for anything not modeled above yet
    }


def _display_name(client: dict) -> str:
    if client.get("IsClientACompany"):
        return client.get("Company") or client.get("ClientRef", "Unknown")
    name = f"{client.get('FirstName', '')} {client.get('LastName', '')}".strip()
    return name or client.get("ClientRef", "Unknown")
