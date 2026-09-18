"""
Resolves a fund's look-through breakdown, so a fund position can
contribute its *underlying* asset-class/country/currency/industry
exposure instead of just "this is a fund" — without this, SAA deviation
and concentration numbers are wrong for any portfolio holding funds.
"""
from __future__ import annotations

from .reference_index import ReferenceIndex

DIMENSION_TO_FIELD = {
    "AssetClass": "AssetClassName",
    "CurrencyGroup": "CurrencyGroupName",
    "CountryGroup": "CountryGroupName",
    "Industry": "IndustryName",
}


def is_look_through_eligible(security_id: int, ref: ReferenceIndex) -> bool:
    security = ref.security(security_id)
    return bool(security and security.get("IsUnbundlingEnabled"))


def fund_breakdown(
    security_id: int, dimension: str, ref: ReferenceIndex
) -> list[tuple[str, float]]:
    """
    Returns [(saa_category_name, weight_fraction), ...] for one fund and
    one dimension ("AssetClass" | "CurrencyGroup" | "CountryGroup" |
    "Industry"), normalized to fractions (0-1) even though the source
    field (FundUnbundlingMappings[].Weight) is in percentage points
    (0-100).

    FundUnbundlingMappings only carries the plain (finer) category name
    for each row (e.g. "Equities EmMa"), not an SAA_*-rolled-up
    equivalent, so it's translated here via ReferenceIndex.to_saa_category
    before being returned — callers should never see the plain name, or
    an SAA deviation computed from this breakdown would silently create
    phantom categories instead of matching the fund's real target bucket.
    A row whose plain category has no direct (plain -> SAA) pair anywhere
    in Securities[] falls back to ReferenceIndex.catch_all_saa_category
    (e.g. an exotic currency that only ever appears inside fund
    breakdowns, never as a security's own classification) when that
    fallback can be determined unambiguously; otherwise it's dropped
    rather than passed through untranslated, since an unrecognized
    bucket would misrepresent the fund's actual SAA exposure.

    Returns [] if the security isn't unbundling-enabled, or no mapping
    rows exist for the requested dimension (a fund can have rows for
    some dimensions and not others).
    """
    field = DIMENSION_TO_FIELD.get(dimension)
    if field is None:
        raise ValueError(f"Unknown dimension: {dimension!r}")

    if not is_look_through_eligible(security_id, ref):
        return []

    rows = ref.fund_unbundling(security_id)
    result = []
    for row in rows:
        plain_category = row.get(field)
        if plain_category is None:
            continue
        saa_category = ref.to_saa_category(dimension, plain_category)
        if saa_category is None:
            saa_category = ref.catch_all_saa_category(dimension)
        if saa_category is None:
            continue  # untranslatable, no safe catch-all — dropped
        result.append((saa_category, row.get("Weight", 0.0) / 100.0))
    return result
