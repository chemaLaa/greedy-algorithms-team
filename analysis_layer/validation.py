"""Data-quality checks for the deterministic analysis layer.

The analysis layer must degrade gracefully on tomorrow's unseen partner data.
A bad/missing metric should suppress only the affected fact, not the whole
client briefing.

Statuses
--------
``ok``          usable as-is
``partial``     usable with an explicit caveat / not fully verifiable
``unavailable`` insufficient data for this analysis
``invalid``     internally inconsistent; do not turn into a numerical claim

No LLM calls and no third-party dependencies.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime
import math
from typing import Any, Optional

STATUSES = {"ok", "partial", "unavailable", "invalid"}

INTERACTION_DATE_FIELDS = (
    "LastConsultationDateUtc",
    "LastConsultationDate",
    "LastAdvisoryDateUtc",
    "LastAdvisoryDate",
    "LastInteractionDateUtc",
    "LastInteractionDate",
    "last_consultation_date",
    "last_interaction_date",
)


def _result(status: str, *, reasons: Optional[list[str]] = None, **details: Any) -> dict:
    if status not in STATUSES:
        raise ValueError(f"unknown validation status: {status}")
    return {"status": status, "reasons": reasons or [], **details}


def _finite_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _parse_datetime(value: Any) -> Optional[datetime]:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _parse_date(value: Any) -> Optional[date]:
    dt = _parse_datetime(value)
    return dt.date() if dt is not None else None


def _positions(portfolio: dict) -> list[tuple[str, dict]]:
    """Return security + account positions; either collection may be absent."""
    out: list[tuple[str, dict]] = []
    for p in portfolio.get("SecurityPositions") or []:
        if isinstance(p, dict):
            out.append(("security", p))
    for p in portfolio.get("AccountPositions") or []:
        if isinstance(p, dict):
            out.append(("account", p))
    return out


def validate_performance_history(portfolio: dict) -> dict:
    """Validate dated ``PerformanceHistory[].Value`` observations.

    The supplied schema calls these rows ``Value``.  Unless UnRiskOmega
    explicitly confirms that the series is flow-adjusted performance/NAV,
    downstream code must describe percentage changes as *portfolio-value
    changes*, not investment returns.
    """
    history = portfolio.get("PerformanceHistory")
    if not history:
        return _result(
            "unavailable",
            reasons=["performance_history_missing_or_empty"],
            point_count=0,
            usable_point_count=0,
            return_semantics_confirmed=False,
        )
    if not isinstance(history, list):
        return _result("invalid", reasons=["performance_history_not_a_list"])

    parsed: list[tuple[int, date, float]] = []
    bad_date_indices: list[int] = []
    bad_value_indices: list[int] = []

    for i, point in enumerate(history):
        if not isinstance(point, dict):
            bad_date_indices.append(i)
            bad_value_indices.append(i)
            continue
        dt = _parse_date(point.get("Date"))
        value = point.get("Value")
        if dt is None:
            bad_date_indices.append(i)
        if not _finite_number(value):
            bad_value_indices.append(i)
        if dt is not None and _finite_number(value):
            parsed.append((i, dt, float(value)))

    if not parsed:
        return _result(
            "unavailable",
            reasons=["no_usable_performance_points"],
            point_count=len(history),
            usable_point_count=0,
            bad_date_indices=bad_date_indices,
            bad_value_indices=bad_value_indices,
            return_semantics_confirmed=False,
        )

    dates = [dt for _, dt, _ in parsed]
    duplicate_dates = sorted({d.isoformat() for d, n in Counter(dates).items() if n > 1})
    chronologically_sorted = dates == sorted(dates)

    status = "ok"
    reasons: list[str] = []
    if bad_date_indices or bad_value_indices:
        status = "partial"
        reasons.append("some_history_points_are_unusable")
    if not chronologically_sorted:
        status = "partial"
        reasons.append("history_not_chronologically_sorted")
    if duplicate_dates:
        status = "invalid"
        reasons.append("duplicate_history_dates")

    sorted_dates = sorted(dates)
    gaps = [(b - a).days for a, b in zip(sorted_dates, sorted_dates[1:])]
    median_gap_days = sorted(gaps)[len(gaps) // 2] if gaps else None

    provided_ytd = portfolio.get("PerformanceYTD")
    ytd_status = (
        "provided"
        if _finite_number(provided_ytd)
        else "absent"
        if provided_ytd is None
        else "invalid"
    )

    return _result(
        status,
        reasons=reasons,
        point_count=len(history),
        usable_point_count=len(parsed),
        chronologically_sorted=chronologically_sorted,
        duplicate_dates=duplicate_dates,
        bad_date_indices=bad_date_indices,
        bad_value_indices=bad_value_indices,
        earliest_date=sorted_dates[0].isoformat(),
        latest_date=sorted_dates[-1].isoformat(),
        median_gap_days=median_gap_days,
        value_semantics="portfolio_value_observation",
        return_semantics_confirmed=False,
        performance_ytd_field=ytd_status,
    )


def validate_current_portfolio_metrics(portfolio: dict) -> dict:
    """Validate current portfolio metrics shown conceptually in the URO UI.

    ``Volatility`` is risk, ``ExpectedReturn`` is a forward-looking expectation,
    and ``ValueAtRisk`` is a risk metric.  None is treated as an actual historic
    performance figure.
    """
    specs = {
        "volatility": ("Volatility", True),
        "expected_return": ("ExpectedReturn", False),
        "value_at_risk": ("ValueAtRisk", True),
    }
    values: dict[str, Optional[float]] = {}
    invalid: list[str] = []
    missing: list[str] = []

    for output_name, (source_name, must_be_nonnegative) in specs.items():
        value = portfolio.get(source_name)
        if value is None:
            values[output_name] = None
            missing.append(source_name)
            continue
        if not _finite_number(value):
            values[output_name] = None
            invalid.append(source_name)
            continue
        f = float(value)
        if must_be_nonnegative and f < 0:
            values[output_name] = None
            invalid.append(source_name)
            continue
        values[output_name] = f

    if invalid:
        status = "partial"
        reasons = ["some_current_metrics_invalid"]
    elif len(missing) == len(specs):
        status = "unavailable"
        reasons = ["current_risk_return_metrics_missing"]
    elif missing:
        status = "partial"
        reasons = ["some_current_metrics_missing"]
    else:
        status = "ok"
        reasons = []

    return _result(status, reasons=reasons, missing_fields=missing, invalid_fields=invalid, **values)


def validate_liquidity(portfolio: dict, *, reconciliation_tolerance: float = 0.01) -> dict:
    """Validate portfolio AUM/liquidity and derive a liquidity ratio when possible."""
    aum = portfolio.get("AssetsUnderManagementInDefaultCurrency")
    liquidity = portfolio.get("LiquidityInDefaultCurrency")

    if aum is None or liquidity is None:
        return _result(
            "unavailable",
            reasons=["aum_or_liquidity_missing"],
            aum=aum if _finite_number(aum) else None,
            liquidity=liquidity if _finite_number(liquidity) else None,
            liquidity_ratio=None,
        )
    if not _finite_number(aum) or not _finite_number(liquidity):
        return _result("invalid", reasons=["aum_or_liquidity_invalid"])

    aum = float(aum)
    liquidity = float(liquidity)
    if aum == 0:
        return _result(
            "unavailable",
            reasons=["aum_zero_cannot_compute_liquidity_ratio"],
            aum=aum,
            liquidity=liquidity,
            liquidity_ratio=None,
        )

    ratio = liquidity / aum
    reasons: list[str] = []
    status = "ok"
    # Do not reject negative liquidity automatically (overdrafts can exist), but
    # surface it.  A ratio materially above 100% is more likely inconsistent.
    if ratio < 0:
        status = "partial"
        reasons.append("negative_liquidity_ratio")
    if ratio > 1.0 + reconciliation_tolerance:
        status = "partial"
        reasons.append("liquidity_exceeds_aum")

    return _result(
        status,
        reasons=reasons,
        aum=aum,
        liquidity=liquidity,
        liquidity_ratio=ratio,
    )


def validate_portfolio_weights(portfolio: dict, *, tolerance: float = 0.005) -> dict:
    """Check whether reported position weights approximately reconcile to 100%.

    Security and account positions are both included. Negative weights are
    reported but not rejected: short/hedging exposures can be legitimate.
    """
    positions = _positions(portfolio)
    if not positions:
        return _result("unavailable", reasons=["no_positions"], position_count=0)

    missing_count = 0
    invalid_count = 0
    weights: list[float] = []
    negative_count = 0

    for _, pos in positions:
        w = pos.get("PortfolioValuePercentage")
        if w is None:
            missing_count += 1
            continue
        if not _finite_number(w):
            invalid_count += 1
            continue
        w = float(w)
        weights.append(w)
        if w < 0:
            negative_count += 1

    if not weights:
        return _result("unavailable", reasons=["no_usable_position_weights"], position_count=len(positions))

    total = sum(weights)
    delta = total - 1.0
    reconciles = abs(delta) <= tolerance
    status = "ok"
    reasons: list[str] = []
    if invalid_count or missing_count:
        status = "partial"
        reasons.append("some_position_weights_missing_or_invalid")
    if not reconciles:
        status = "partial"
        reasons.append("position_weights_do_not_reconcile_to_one")

    return _result(
        status,
        reasons=reasons,
        position_count=len(positions),
        usable_weight_count=len(weights),
        weight_sum=total,
        difference_from_one=delta,
        tolerance=tolerance,
        reconciles=reconciles,
        negative_weight_count=negative_count,
        missing_weight_count=missing_count,
        invalid_weight_count=invalid_count,
    )


def validate_risk_contributions(
    portfolio: dict,
    *,
    rel_tolerance: float = 0.01,
    abs_tolerance: float = 1e-4,
) -> dict:
    """Validate ``ContributionVolatility`` against portfolio ``Volatility``.

    Security *and account* positions participate. Negative contribution is
    valid and is not clipped; diversification/hedging can make a component's
    risk contribution negative.
    """
    positions = _positions(portfolio)
    vol = portfolio.get("Volatility")

    contributions: list[float] = []
    missing_count = 0
    invalid_count = 0
    negative_count = 0
    security_count = 0
    account_count = 0

    for kind, pos in positions:
        cv = pos.get("ContributionVolatility")
        if cv is None:
            missing_count += 1
            continue
        if not _finite_number(cv):
            invalid_count += 1
            continue
        cv = float(cv)
        contributions.append(cv)
        security_count += int(kind == "security")
        account_count += int(kind == "account")
        if cv < 0:
            negative_count += 1

    if vol is not None and (not _finite_number(vol) or float(vol) < 0):
        return _result(
            "invalid",
            reasons=["portfolio_volatility_invalid"],
            portfolio_volatility=vol,
            contribution_count=len(contributions),
        )

    if not contributions:
        return _result(
            "unavailable",
            reasons=["risk_contributions_missing"],
            portfolio_volatility=float(vol) if _finite_number(vol) else None,
            contribution_count=0,
            security_contribution_count=0,
            account_contribution_count=0,
            missing_contribution_count=missing_count,
            invalid_contribution_count=invalid_count,
        )

    contribution_sum = sum(contributions)
    gross_contribution = sum(abs(x) for x in contributions)

    if vol is None:
        return _result(
            "partial",
            reasons=["portfolio_volatility_missing_cannot_reconcile_contributions"],
            portfolio_volatility=None,
            contribution_sum=contribution_sum,
            gross_contribution=gross_contribution,
            contribution_count=len(contributions),
            security_contribution_count=security_count,
            account_contribution_count=account_count,
            negative_contribution_count=negative_count,
            missing_contribution_count=missing_count,
            invalid_contribution_count=invalid_count,
            reconciles=None,
        )

    vol = float(vol)
    tolerance = max(abs_tolerance, rel_tolerance * abs(vol))

    if vol > tolerance and abs(contribution_sum) <= abs_tolerance and gross_contribution <= abs_tolerance:
        return _result(
            "unavailable",
            reasons=["risk_contributions_not_populated"],
            portfolio_volatility=vol,
            contribution_sum=contribution_sum,
            gross_contribution=gross_contribution,
            contribution_count=len(contributions),
            security_contribution_count=security_count,
            account_contribution_count=account_count,
            negative_contribution_count=negative_count,
            missing_contribution_count=missing_count,
            invalid_contribution_count=invalid_count,
            reconciles=False,
            tolerance=tolerance,
        )

    difference = contribution_sum - vol
    reconciles = abs(difference) <= tolerance

    status = "ok"
    reasons: list[str] = []
    if invalid_count:
        status = "partial"
        reasons.append("some_risk_contributions_invalid")
    if not reconciles:
        status = "invalid"
        reasons.append("risk_contributions_do_not_reconcile_to_portfolio_volatility")

    return _result(
        status,
        reasons=reasons,
        portfolio_volatility=vol,
        contribution_sum=contribution_sum,
        gross_contribution=gross_contribution,
        difference=difference,
        tolerance=tolerance,
        reconciles=reconciles,
        contribution_count=len(contributions),
        security_contribution_count=security_count,
        account_contribution_count=account_count,
        negative_contribution_count=negative_count,
        missing_contribution_count=missing_count,
        invalid_contribution_count=invalid_count,
    )


def validate_saa_deviations(portfolio: dict) -> dict:
    """Inspect resolved SAA rows without assuming every dimension has bounds."""
    saa = portfolio.get("saa_deviations")
    if not saa:
        return _result("unavailable", reasons=["resolved_saa_deviations_missing_or_empty"], dimensions={})
    if not isinstance(saa, dict):
        return _result("invalid", reasons=["resolved_saa_deviations_not_a_dict"])

    dimensions: dict[str, dict] = {}
    bad_rows: list[dict] = []

    for dimension, rows in saa.items():
        rows = rows or []
        target_count = bounded_count = actual_count = 0
        for i, row in enumerate(rows):
            if not isinstance(row, dict):
                bad_rows.append({"dimension": dimension, "index": i, "reason": "row_not_a_dict"})
                continue
            actual = row.get("actual")
            target = row.get("target")
            min_v = row.get("min", row.get("MinPercentage"))
            max_v = row.get("max", row.get("MaxPercentage"))

            if _finite_number(actual):
                actual_count += 1
            elif actual is not None:
                bad_rows.append({"dimension": dimension, "index": i, "reason": "actual_invalid"})

            if _finite_number(target):
                target_count += 1
            elif target is not None:
                bad_rows.append({"dimension": dimension, "index": i, "reason": "target_invalid"})

            if _finite_number(min_v) or _finite_number(max_v):
                bounded_count += 1
            if min_v is not None and not _finite_number(min_v):
                bad_rows.append({"dimension": dimension, "index": i, "reason": "min_invalid"})
            if max_v is not None and not _finite_number(max_v):
                bad_rows.append({"dimension": dimension, "index": i, "reason": "max_invalid"})

        dimensions[dimension] = {
            "row_count": len(rows),
            "actual_count": actual_count,
            "target_count": target_count,
            "bounded_count": bounded_count,
            "can_compare_to_target": target_count > 0,
            "can_detect_bound_breach": bounded_count > 0,
        }

    return _result(
        "partial" if bad_rows else "ok",
        reasons=["some_saa_rows_invalid"] if bad_rows else [],
        dimensions=dimensions,
        bad_rows=bad_rows,
    )


def _explicit_interaction_date(client: dict) -> tuple[Optional[date], Optional[str]]:
    for field in INTERACTION_DATE_FIELDS:
        if client.get(field) is None:
            continue
        parsed = _parse_date(client.get(field))
        if parsed is not None:
            return parsed, field
    return None, None


def validate_interaction_context(client: dict, portfolio: dict) -> dict:
    """Validate the best available anchor for "since last consultation".

    If tomorrow's dataset exposes a genuine last-consultation field, it is
    preferred. Otherwise the latest ClientNote date is a documented fallback.
    """
    explicit_date, explicit_field = _explicit_interaction_date(client)

    notes = client.get("ClientNotes")
    if notes is None:
        notes = client.get("notes")
    notes = notes or []
    note_dates = [
        d for n in notes if isinstance(n, dict)
        for d in [_parse_date(n.get("CreatedByDateUTC"))] if d is not None
    ]

    if explicit_date is not None:
        interaction_date = explicit_date
        source = explicit_field
        approximation = False
    elif note_dates:
        interaction_date = max(note_dates)
        source = "client_note_proxy"
        approximation = True
    else:
        return _result(
            "unavailable",
            reasons=["interaction_date_unavailable"],
            source=None,
            approximation=None,
            interaction_date=None,
            latest_history_date=None,
        )

    history = portfolio.get("PerformanceHistory") or []
    history_dates = [
        d for h in history if isinstance(h, dict)
        for d in [_parse_date(h.get("Date"))] if d is not None
    ]
    if not history_dates:
        return _result(
            "unavailable",
            reasons=["performance_history_missing_for_interaction_comparison"],
            source=source,
            approximation=approximation,
            interaction_date=interaction_date.isoformat(),
            latest_history_date=None,
        )

    latest_history = max(history_dates)
    if interaction_date > latest_history:
        return _result(
            "unavailable",
            reasons=["interaction_date_after_latest_history_point"],
            source=source,
            approximation=approximation,
            interaction_date=interaction_date.isoformat(),
            latest_history_date=latest_history.isoformat(),
        )

    if approximation:
        return _result(
            "partial",
            reasons=["client_note_used_as_interaction_proxy"],
            source=source,
            approximation=True,
            interaction_date=interaction_date.isoformat(),
            latest_history_date=latest_history.isoformat(),
        )

    return _result(
        "ok",
        reasons=[],
        source=source,
        approximation=False,
        interaction_date=interaction_date.isoformat(),
        latest_history_date=latest_history.isoformat(),
    )


def validate_interaction_proxy(client: dict, portfolio: dict) -> dict:
    """Backward-compatible name; now prefers an explicit consultation field."""
    return validate_interaction_context(client, portfolio)


def validate_portfolio_analysis_inputs(portfolio: dict) -> dict:
    """One quality-gate call for a resolved or raw portfolio."""
    checks = {
        "performance_history": validate_performance_history(portfolio),
        "current_metrics": validate_current_portfolio_metrics(portfolio),
        "liquidity": validate_liquidity(portfolio),
        "weights": validate_portfolio_weights(portfolio),
        "risk": validate_risk_contributions(portfolio),
        "saa": validate_saa_deviations(portfolio),
    }

    statuses = [x["status"] for x in checks.values()]
    overall = "invalid" if "invalid" in statuses else "partial" if any(s in {"partial", "unavailable"} for s in statuses) else "ok"
    return {
        "portfolio_id": portfolio.get("PortfolioId"),
        "portfolio_name": portfolio.get("Name"),
        "status": overall,
        "checks": checks,
    }


def validate_client_analysis_inputs(client_view: dict) -> dict:
    portfolios = client_view.get("portfolios")
    if portfolios is None:
        portfolios = client_view.get("Portfolios") or []
    results = [validate_portfolio_analysis_inputs(p) for p in portfolios]
    return {
        "client_id": client_view.get("ClientId") or client_view.get("client_id"),
        "client_ref": client_view.get("ClientRef") or client_view.get("client_ref"),
        "portfolio_count": len(results),
        "status_counts": dict(Counter(r["status"] for r in results)),
        "portfolios": results,
    }


def _unique_id_check(rows: Any, key: str = "Id") -> dict:
    if not isinstance(rows, list):
        return {"present": False, "count": 0, "duplicate_ids": []}
    ids = [r.get(key) for r in rows if isinstance(r, dict) and r.get(key) is not None]
    duplicates = sorted([value for value, count in Counter(ids).items() if count > 1], key=str)
    return {"present": True, "count": len(rows), "duplicate_ids": duplicates}


def audit_reference_data(reference: dict, clients: Optional[list[dict]] = None) -> dict:
    """Audit reference-table assumptions likely to vary in hidden data."""
    securities = reference.get("Securities") or []
    saas = reference.get("StrategicAssetAllocations") or []
    fund_mappings = reference.get("FundUnbundlingMappings") or []

    sec_ids = {s.get("Id") for s in securities if isinstance(s, dict)}
    sec_by_id = {s.get("Id"): s for s in securities if isinstance(s, dict) and s.get("Id") is not None}
    saa_ids = {s.get("Id") for s in saas if isinstance(s, dict)}

    grouped: dict[Any, list[float]] = defaultdict(list)
    negative_weight_rows = 0
    invalid_weight_rows = 0
    for row in fund_mappings:
        if not isinstance(row, dict):
            invalid_weight_rows += 1
            continue
        w = row.get("Weight")
        fid = row.get("FundSecurityId")
        if not _finite_number(w) or fid is None:
            invalid_weight_rows += 1
            continue
        w = float(w)
        grouped[fid].append(w)
        if w < 0:
            negative_weight_rows += 1

    scale_counts = Counter()
    suspicious_funds: list[dict] = []
    for fid, weights in grouped.items():
        total = sum(weights)
        if math.isclose(total, 100.0, rel_tol=0.0, abs_tol=0.05):
            scale = "percent_0_100"
        elif math.isclose(total, 1.0, rel_tol=0.0, abs_tol=0.005):
            scale = "fraction_0_1"
        else:
            scale = "suspicious"
            suspicious_funds.append({"FundSecurityId": fid, "weight_sum": total, "row_count": len(weights)})
        scale_counts[scale] += 1

    saa_dimensions: dict[str, Counter] = defaultdict(Counter)
    for saa in saas:
        for mapping in saa.get("Mappings") or []:
            if not isinstance(mapping, dict):
                continue
            dimension = mapping.get("Dimension") or "<missing>"
            signature = tuple(
                name for name in ("MinPercentage", "TargetPercentage", "MaxPercentage")
                if _finite_number(mapping.get(name))
            )
            saa_dimensions[dimension][signature] += 1

    referenced_saa_missing: set[Any] = set()
    referenced_security_missing: set[Any] = set()
    held_unbundling_without_mapping: set[Any] = set()
    held_security_ids: set[Any] = set()

    if clients:
        mapped_fund_ids = set(grouped)
        for client in clients:
            for portfolio in client.get("Portfolios") or []:
                sid = portfolio.get("StrategicAssetAllocationId")
                if sid is not None and sid not in saa_ids:
                    referenced_saa_missing.add(sid)
                for pos in portfolio.get("SecurityPositions") or []:
                    sec_id = pos.get("SecurityId")
                    if sec_id is None:
                        continue
                    held_security_ids.add(sec_id)
                    sec = sec_by_id.get(sec_id)
                    if sec is None:
                        referenced_security_missing.add(sec_id)
                    elif sec.get("IsUnbundlingEnabled") and sec_id not in mapped_fund_ids:
                        held_unbundling_without_mapping.add(sec_id)

    held_secs = [sec_by_id[i] for i in held_security_ids if i in sec_by_id]
    useful_security_fields = [
        "MaturityDateUtc",
        "PRC",
        "SecurityInvestRatingName",
        "InRecommendationList",
        "SustainabilityScore",
        "Volatility",
        "EndOfDayPrice",
        "PriceDateUtc",
    ]
    held_field_coverage = {
        field: {
            "present": sum(s.get(field) is not None for s in held_secs),
            "held_security_count": len(held_secs),
        }
        for field in useful_security_fields
    }

    return {
        "collections": {
            "Securities": _unique_id_check(securities),
            "StrategicAssetAllocations": _unique_id_check(saas),
            "SuitabilityRules": _unique_id_check(reference.get("SuitabilityRules") or []),
            "RecommendationLists": _unique_id_check(reference.get("RecommendationLists") or []),
        },
        "fund_lookthrough": {
            "mapping_row_count": len(fund_mappings),
            "fund_count": len(grouped),
            "scale_counts": dict(scale_counts),
            "negative_weight_row_count": negative_weight_rows,
            "invalid_weight_row_count": invalid_weight_rows,
            "suspicious_funds": suspicious_funds[:50],
            "held_unbundling_without_mapping": sorted(held_unbundling_without_mapping, key=str),
        },
        "saa": {
            "dimension_signatures": {
                dim: {"+".join(sig) if sig else "none": count for sig, count in counts.items()}
                for dim, counts in saa_dimensions.items()
            },
            "referenced_saa_ids_missing_from_reference": sorted(referenced_saa_missing, key=str),
        },
        "held_security_metadata": {
            "unique_held_security_count": len(held_security_ids),
            "missing_from_reference": sorted(referenced_security_missing, key=str),
            "field_coverage": held_field_coverage,
        },
        "orphan_fund_mapping_ids": sorted([fid for fid in grouped if fid not in sec_ids], key=str)[:100],
    }


def audit_dataset(clients: list[dict], reference: Optional[dict] = None) -> dict:
    """Pre-flight audit for a newly received partner dataset."""
    portfolio_results: list[dict] = []
    field_presence = Counter()
    portfolio_count = 0

    watched_fields = [
        "Volatility",
        "ExpectedReturn",
        "ValueAtRisk",
        "PerformanceYTD",
        "PerformanceHistory",
        "LiquidityInDefaultCurrency",
        "AssetsUnderManagementInDefaultCurrency",
        "SecurityPositions",
        "AccountPositions",
    ]

    for client in clients or []:
        for portfolio in client.get("Portfolios") or []:
            portfolio_count += 1
            for field in watched_fields:
                if field in portfolio and portfolio.get(field) is not None:
                    field_presence[field] += 1

            checks = {
                "performance_history": validate_performance_history(portfolio),
                "current_metrics": validate_current_portfolio_metrics(portfolio),
                "liquidity": validate_liquidity(portfolio),
                "weights": validate_portfolio_weights(portfolio),
                "risk": validate_risk_contributions(portfolio),
                "interaction_context": validate_interaction_context(client, portfolio),
            }
            statuses = [c["status"] for c in checks.values()]
            overall = "invalid" if "invalid" in statuses else "partial" if any(s in {"partial", "unavailable"} for s in statuses) else "ok"
            portfolio_results.append({
                "client_ref": client.get("ClientRef"),
                "portfolio_id": portfolio.get("PortfolioId"),
                "portfolio_name": portfolio.get("Name"),
                "status": overall,
                "checks": checks,
            })

    check_names = [
        "performance_history",
        "current_metrics",
        "liquidity",
        "weights",
        "risk",
        "interaction_context",
    ]
    check_status_counts = {
        name: dict(Counter(p["checks"][name]["status"] for p in portfolio_results))
        for name in check_names
    }

    issues = []
    for p in portfolio_results:
        for name, check in p["checks"].items():
            if check["status"] != "ok":
                issues.append({
                    "client_ref": p.get("client_ref"),
                    "portfolio_id": p.get("portfolio_id"),
                    "check": name,
                    "status": check["status"],
                    "reasons": check.get("reasons") or [],
                })

    explicit_interaction_counts = {
        field: sum(c.get(field) is not None for c in clients or [])
        for field in INTERACTION_DATE_FIELDS
    }
    client_field_presence = {
        "ProfilingDateUtc": sum(c.get("ProfilingDateUtc") is not None for c in clients or []),
        "ClientNotes": sum(bool(c.get("ClientNotes")) for c in clients or []),
        "SuitabilityViolations": sum(bool(c.get("SuitabilityViolations")) for c in clients or []),
        "Proposals": sum(bool(c.get("Proposals")) for c in clients or []),
        "explicit_interaction_fields": explicit_interaction_counts,
    }

    ref_audit = audit_reference_data(reference, clients) if reference is not None else None
    held_meta = (ref_audit or {}).get("held_security_metadata", {})
    held_cov = held_meta.get("field_coverage", {})

    # UI/challenge capability map: useful when a new export arrives tomorrow.
    capabilities = {
        "historical_value_series": field_presence["PerformanceHistory"] == portfolio_count and portfolio_count > 0,
        "actual_performance_ytd_provided": field_presence["PerformanceYTD"] > 0,
        "current_risk_volatility": field_presence["Volatility"] > 0,
        "expected_return": field_presence["ExpectedReturn"] > 0,
        "value_at_risk": field_presence["ValueAtRisk"] > 0,
        "liquidity": field_presence["LiquidityInDefaultCurrency"] > 0,
        "explicit_last_consultation": any(explicit_interaction_counts.values()),
        "client_note_interaction_proxy": client_field_presence["ClientNotes"] > 0,
        "suitability_violations": client_field_presence["SuitabilityViolations"] > 0,
        "proposals": client_field_presence["Proposals"] > 0,
        "security_maturities": held_cov.get("MaturityDateUtc", {}).get("present", 0) > 0,
        "product_risk_prc": held_cov.get("PRC", {}).get("present", 0) > 0,
        "recommendation_list_membership": held_cov.get("InRecommendationList", {}).get("present", 0) > 0,
        "security_investment_rating": held_cov.get("SecurityInvestRatingName", {}).get("present", 0) > 0,
        "sustainability_scores": held_cov.get("SustainabilityScore", {}).get("present", 0) > 0,
    }

    return {
        "client_count": len(clients or []),
        "portfolio_count": len(portfolio_results),
        "portfolio_status_counts": dict(Counter(p["status"] for p in portfolio_results)),
        "check_status_counts": check_status_counts,
        "portfolio_field_presence": {
            field: {"present": field_presence[field], "portfolio_count": portfolio_count}
            for field in watched_fields
        },
        "client_field_presence": client_field_presence,
        "capabilities": capabilities,
        "issues": issues,
        "reference": ref_audit,
    }
