"""
Resolves a client's currently-active suitability violations: filters out
anything covered by an explicit per-client rule override, and attaches
the full rule definition from reference.json.
"""
from __future__ import annotations

from .reference_index import ReferenceIndex


def active_violations(client: dict, ref: ReferenceIndex) -> list[dict]:
    """
    Returns each SuitabilityViolations[] entry enriched with the matching
    SuitabilityRules[] row (under "rule", None if unresolvable).

    A violation is dropped entirely if its RuleCode appears in the
    client's IndividualRuleOverrides — that rule has been explicitly
    waived for this specific client, so surfacing it as an active issue
    in a briefing would be misleading, even though the raw violation
    record is still present in the source data.
    """
    overridden_codes = {
        o.get("RuleCode") for o in client.get("IndividualRuleOverrides") or [] if o.get("RuleCode")
    }

    result = []
    for violation in client.get("SuitabilityViolations") or []:
        rule_code = violation.get("RuleCode")
        if rule_code in overridden_codes:
            continue
        result.append({**violation, "rule": ref.suitability_rule(rule_code)})
    return result
