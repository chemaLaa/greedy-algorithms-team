from helpers import first_client
from data_layer.violations import active_violations


def test_overridden_violation_is_filtered_out():
    client, ref = first_client()
    result = active_violations(client, ref)
    codes = [v["RuleCode"] for v in result]

    # Fixture: client has 2 raw violations (MAX_SINGLE_POSITION,
    # CURRENCY_CONCENTRATION) but overrides CURRENCY_CONCENTRATION
    # specifically — only the non-overridden one should survive.
    assert "MAX_SINGLE_POSITION" in codes
    assert "CURRENCY_CONCENTRATION" not in codes
    assert len(codes) == 1


def test_surviving_violation_has_rule_attached():
    client, ref = first_client()
    result = active_violations(client, ref)
    violation = result[0]
    assert violation["rule"] is not None
    assert violation["rule"]["RuleCode"] == "MAX_SINGLE_POSITION"


def test_no_violations_returns_empty_list():
    _, ref = first_client()
    client_without_violations = {"SuitabilityViolations": [], "IndividualRuleOverrides": []}
    assert active_violations(client_without_violations, ref) == []


def test_missing_violations_key_returns_empty_list():
    _, ref = first_client()
    assert active_violations({}, ref) == []
