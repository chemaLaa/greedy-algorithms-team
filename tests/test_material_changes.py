from datetime import date

from analysis_layer.material_changes import change_since_last_interaction, last_interaction_date


def test_last_interaction_ignores_bad_note_dates():
    notes = [
        {"CreatedByDateUTC": "not-a-date"},
        {"CreatedByDateUTC": "2026-05-01T10:00:00Z"},
        {"CreatedByDateUTC": "2026-06-01T10:00:00Z"},
    ]
    assert last_interaction_date(notes) == date(2026, 6, 1)


def test_interaction_after_latest_history_is_not_zero_change():
    p = {
        "PerformanceHistory": [
            {"Date": "2026-06-01", "Value": 100.0},
            {"Date": "2026-07-01", "Value": 110.0},
        ]
    }
    result = change_since_last_interaction(p, date(2026, 9, 1))
    assert result["status"] == "unavailable"
    assert result["reason"] == "interaction_after_latest_history_point"
    assert result["change"] is None


def test_valid_proxy_change_is_marked_approximate():
    p = {
        "PerformanceHistory": [
            {"Date": "2026-04-01", "Value": 100.0},
            {"Date": "2026-06-01", "Value": 105.0},
            {"Date": "2026-07-01", "Value": 110.0},
        ]
    }
    result = change_since_last_interaction(p, date(2026, 6, 15))
    assert result["status"] == "partial"
    assert result["approximation"] is True
    assert result["change"] == 5.0
