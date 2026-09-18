"""
Builds fast, id-keyed lookup indices over reference.json's collections.

Every collection in reference.json may be entirely absent from a given
export (see DATA.md: it's trimmed to only what the paired clients.json
actually references). All lookups here return None / [] / False rather
than raising when data is missing, so callers can treat "no data" as a
normal case instead of special-casing it everywhere.
"""
from __future__ import annotations

from typing import Any, Optional


class ReferenceIndex:
    def __init__(self, reference: dict[str, Any]):
        reference = reference or {}

        self.securities = self._index_by(reference, "Securities", "Id")
        self.risk_profiles = self._index_by(reference, "RiskProfiles", "Id")
        self.esg_profiles = self._index_by(reference, "EsgProfiles", "Id")
        self.investment_services = self._index_by(reference, "InvestmentServices", "Id")
        self.strategies = self._index_by(reference, "Strategies", "Id")
        self.strategic_asset_allocations = self._index_by(
            reference, "StrategicAssetAllocations", "Id"
        )
        self.suitability_rules = self._index_by(reference, "SuitabilityRules", "RuleCode")
        self.tags = self._index_by(reference, "Tags", "Name")
        self.proposal_statuses = self._index_by(reference, "ProposalStatuses", "Id")
        self.advisory_types = self._index_by(reference, "AdvisoryTypes", "Id")
        self.recommendation_lists = reference.get("RecommendationLists") or []

        # FundUnbundlingMappings has no single Id of its own; group by the
        # fund security it describes so a lookup returns all rows at once.
        self.fund_unbundling_by_security: dict[int, list[dict]] = {}
        for row in reference.get("FundUnbundlingMappings") or []:
            fund_id = row.get("FundSecurityId")
            if fund_id is None:
                continue
            self.fund_unbundling_by_security.setdefault(fund_id, []).append(row)

        self.recommended_security_ids: set[int] = {
            sec.get("SecurityId")
            for lst in self.recommendation_lists
            for sec in (lst.get("Securities") or [])
            if sec.get("SecurityId") is not None
        }

        # FundUnbundlingMappings only carries the *plain*, finer category
        # names (e.g. "Equities EmMa"), not an SAA_*-rolled-up equivalent —
        # there's no such field on those rows. To compare a fund's
        # look-through breakdown against SAA targets, those plain names
        # need translating into the same coarse buckets Securities[] uses
        # for its own SAA_* fields (e.g. "Shares"). That translation isn't
        # provided directly anywhere, but it's derivable: every security
        # that has both the plain and SAA_* field for a dimension gives us
        # one (plain -> SAA) pair, and in practice a plain name maps to
        # exactly one SAA name across the whole dataset.
        self._plain_to_saa: dict[str, dict[str, str]] = {
            "AssetClass": self._build_plain_to_saa(reference, "AssetClassName", "SAA_AssetClassName"),
            "CurrencyGroup": self._build_plain_to_saa(
                reference, "CurrencyGroupName", "SAA_CurrencyGroupName"
            ),
            "CountryGroup": self._build_plain_to_saa(
                reference, "CountryGroupName", "SAA_CountryGroupName"
            ),
            "Industry": self._build_plain_to_saa(reference, "IndustryName", "SAA_IndustryName"),
        }

    @staticmethod
    def _build_plain_to_saa(reference: dict, plain_field: str, saa_field: str) -> dict[str, str]:
        mapping: dict[str, str] = {}
        for s in reference.get("Securities") or []:
            plain = s.get(plain_field)
            saa = s.get(saa_field)
            if plain is not None and saa is not None:
                mapping[plain] = saa  # last-write-wins; verified conflict-free on real data
        return mapping

    @staticmethod
    def _index_by(reference: dict, collection_name: str, key_field: str) -> dict:
        rows = reference.get(collection_name) or []
        return {row[key_field]: row for row in rows if key_field in row}

    # --- convenience getters, all defensive against missing ids/rows ---

    def security(self, security_id: Optional[int]) -> Optional[dict]:
        return None if security_id is None else self.securities.get(security_id)

    def risk_profile(self, risk_profile_id: Optional[int]) -> Optional[dict]:
        return None if risk_profile_id is None else self.risk_profiles.get(risk_profile_id)

    def esg_profile(self, esg_profile_id: Optional[int]) -> Optional[dict]:
        return None if esg_profile_id is None else self.esg_profiles.get(esg_profile_id)

    def investment_service(self, service_id: Optional[int]) -> Optional[dict]:
        return None if service_id is None else self.investment_services.get(service_id)

    def strategy(self, strategy_id: Optional[int]) -> Optional[dict]:
        return None if strategy_id is None else self.strategies.get(strategy_id)

    def saa(self, saa_id: Optional[int]) -> Optional[dict]:
        return None if saa_id is None else self.strategic_asset_allocations.get(saa_id)

    def suitability_rule(self, rule_code: Optional[str]) -> Optional[dict]:
        return None if rule_code is None else self.suitability_rules.get(rule_code)

    def proposal_status(self, status_id: Optional[int]) -> Optional[dict]:
        return None if status_id is None else self.proposal_statuses.get(status_id)

    def advisory_type(self, type_id: Optional[int]) -> Optional[dict]:
        return None if type_id is None else self.advisory_types.get(type_id)

    def fund_unbundling(self, fund_security_id: Optional[int]) -> list[dict]:
        if fund_security_id is None:
            return []
        return self.fund_unbundling_by_security.get(fund_security_id, [])

    def is_recommended(self, security_id: Optional[int]) -> bool:
        return security_id in self.recommended_security_ids

    def to_saa_category(self, dimension: str, plain_category: Optional[str]) -> Optional[str]:
        """
        Translates a plain (fine-grained) category name — as used in
        FundUnbundlingMappings[] — into the coarse SAA_* bucket name it
        rolls up to for the given dimension. Returns None if no security
        in this dataset links that plain name to an SAA name (i.e. the
        translation can't be derived), so callers can decide whether to
        drop, flag, or fall back for that row rather than silently
        mis-bucketing it.
        """
        return self._plain_to_saa.get(dimension, {}).get(plain_category)

    def catch_all_saa_category(self, dimension: str) -> Optional[str]:
        """
        Best-effort guess at a dimension's "everything else" SAA bucket —
        for translating a plain category that has no derivable (plain ->
        SAA) pair at all, which happens when that category only ever
        shows up inside a fund's look-through breakdown (e.g. an exotic
        currency no client happens to hold directly), never as any
        security's own classification.

        Heuristic: an SAA category name that is a translation *target*
        but never itself a plain category name in this dataset is very
        likely a catch-all/aggregation bucket (e.g. "Other") rather than
        a proper 1:1-mapped category — every 1:1 category keeps its own
        name on both sides (e.g. "Euro" -> "Euro"). Returns the bucket
        only if there's exactly one such candidate, to avoid guessing
        under ambiguity; returns None otherwise, in which case the
        caller should drop the row rather than risk mis-bucketing it.
        """
        translation = self._plain_to_saa.get(dimension, {})
        plain_names = set(translation.keys())
        saa_names = set(translation.values())
        candidates = saa_names - plain_names
        return next(iter(candidates)) if len(candidates) == 1 else None
