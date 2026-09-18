from datetime import date

from analysis_layer.material_changes import last_interaction_date, change_since_last_interaction


def test_last_interaction_date_picks_the_latest_note():
    notes = [
        {"Note": "old", "CreatedByDateUTC": "2026-01-01T00:00:00Z"},
        {"Note": "newest", "CreatedByDateUTC": "2026-06-15T00:00:00Z"},
        {"Note": "middle", "CreatedByDateUTC": "2026-03-01T00:00:00Z"},
    ]
    assert last_interaction_date(notes) == date(2026, 6, 15)


def test_last_interaction_date_empty_notes_returns_none():
    assert last_interaction_date([]) is None


def test_change_since_last_interaction_finds_the_point_before():
    portfolio = {
        "PerformanceHistory": [
            {"Date": "2026-06-01", "Value": 100000},
            {"Date": "2026-07-01", "Value": 110000},
            {"Date": "2026-08-01", "Value": 105000},
        ]
    }
    result = change_since_last_interaction(portfolio, date(2026, 7, 15))
    # Last point on-or-before 2026-07-15 is 2026-07-01 (110000); latest is
    # 2026-08-01 (105000).
    assert result["value_then"] == 110000
    assert result["value_now"] == 105000
    assert result["change"] == -5000


def test_change_since_last_interaction_none_since_date():
    portfolio = {"PerformanceHistory": [{"Date": "2026-08-01", "Value": 100}]}
    result = change_since_last_interaction(portfolio, None)
    assert result["change"] is None
    assert result["value_then"] is None


def test_change_since_last_interaction_since_predates_all_history():
    portfolio = {"PerformanceHistory": [{"Date": "2026-08-01", "Value": 100}]}
    result = change_since_last_interaction(portfolio, date(2020, 1, 1))
    assert result["value_then"] is None
    assert result["value_now"] == 100
    assert result["change"] is None
