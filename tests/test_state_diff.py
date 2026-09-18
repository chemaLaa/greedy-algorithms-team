from state.diff import diff_portfolio_snapshots


def _snapshot(**overrides):
    base = {
        "portfolio_id": 1,
        "captured_at": "2026-01-01T00:00:00+00:00",
        "portfolio_value": 100000.0,
        "allocation": {"AssetClass": {"Shares": 0.5, "Bonds": 0.5}},
        "top_positions": [
            {"SecurityId": 1, "SecurityName": "A", "weight": 0.3},
            {"SecurityId": 2, "SecurityName": "B", "weight": 0.2},
        ],
        "violations": ["RULE_A", "RULE_B"],
    }
    base.update(overrides)
    return base


def test_first_interaction_when_no_previous_snapshot():
    current = _snapshot()
    diff = diff_portfolio_snapshots(None, current)
    assert diff["is_first_interaction"] is True
    assert diff["violations_new"] == current["violations"]
    assert diff["violations_resolved"] == []
    assert diff["portfolio_value_change"] is None


def test_no_change_gives_empty_diff():
    snap = _snapshot()
    diff = diff_portfolio_snapshots(snap, snap)
    assert diff["is_first_interaction"] is False
    assert diff["violations_new"] == []
    assert diff["violations_resolved"] == []
    assert diff["allocation_changes"] == {}
    assert diff["portfolio_value_change"]["change"] == 0


def test_detects_new_and_resolved_violations():
    previous = _snapshot(violations=["RULE_A", "RULE_B"])
    current = _snapshot(violations=["RULE_B", "RULE_C"])
    diff = diff_portfolio_snapshots(previous, current)
    assert diff["violations_new"] == ["RULE_C"]
    assert diff["violations_resolved"] == ["RULE_A"]


def test_detects_portfolio_value_change():
    previous = _snapshot(portfolio_value=100000.0)
    current = _snapshot(portfolio_value=108000.0)
    diff = diff_portfolio_snapshots(previous, current)
    change = diff["portfolio_value_change"]
    assert change["change"] == 8000.0
    assert abs(change["change_pct"] - 0.08) < 1e-9


def test_allocation_change_above_epsilon_is_reported():
    previous = _snapshot(allocation={"AssetClass": {"Shares": 0.50}})
    current = _snapshot(allocation={"AssetClass": {"Shares": 0.56}})
    diff = diff_portfolio_snapshots(previous, current)
    assert abs(diff["allocation_changes"]["AssetClass"]["Shares"]["change"] - 0.06) < 1e-9


def test_allocation_change_below_epsilon_is_ignored():
    previous = _snapshot(allocation={"AssetClass": {"Shares": 0.50}})
    current = _snapshot(allocation={"AssetClass": {"Shares": 0.501}})  # 0.1pt, below 0.5pt epsilon
    diff = diff_portfolio_snapshots(previous, current)
    assert diff["allocation_changes"] == {}


def test_position_entered_and_exited_top():
    previous = _snapshot(
        top_positions=[{"SecurityId": 1, "SecurityName": "A", "weight": 0.3}]
    )
    current = _snapshot(
        top_positions=[{"SecurityId": 2, "SecurityName": "B", "weight": 0.4}]
    )
    diff = diff_portfolio_snapshots(previous, current)
    assert diff["position_changes"]["entered_top"][0]["SecurityName"] == "B"
    assert diff["position_changes"]["exited_top"][0]["SecurityName"] == "A"
