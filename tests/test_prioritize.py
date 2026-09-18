from helpers import first_client
from data_layer import build_client_view
from analysis_layer.prioritize import build_client_priorities, build_portfolio_priorities


def test_build_client_priorities_returns_one_bundle_per_portfolio():
    client, ref = first_client()
    view = build_client_view(client, ref)
    priorities = build_client_priorities(view, ref)
    assert len(priorities) == len(view["portfolios"])


def test_priorities_include_active_violation():
    client, ref = first_client()
    view = build_client_view(client, ref)
    priorities = build_client_priorities(view, ref)[0]

    types = [p["type"] for p in priorities["priorities"]]
    # Fixture: MAX_SINGLE_POSITION survives override filtering (see
    # test_violations.py), should show up here as a violation item.
    assert "violation" in types


def test_priorities_include_saa_breach():
    client, ref = first_client()
    view = build_client_view(client, ref)
    priorities = build_client_priorities(view, ref)[0]

    deviation_items = [p for p in priorities["priorities"] if p["type"] == "saa_deviation"]
    # Fixture: Bonds breaches its min (0.10 actual vs 0.30 min).
    assert any(item["category"] == "Bonds" and item["breach"] == "min" for item in deviation_items)


def test_priorities_sorted_errors_before_warnings():
    client, ref = first_client()
    view = build_client_view(client, ref)
    priorities = build_client_priorities(view, ref)[0]

    ranks = [p["rank"] for p in priorities["priorities"]]
    assert ranks == sorted(ranks, reverse=True)


def test_concentration_flag_above_threshold():
    client, ref = first_client()
    view = build_client_view(client, ref)
    priorities = build_client_priorities(view, ref)[0]

    # Fixture: Nestle is 35% of the portfolio, above the 20% threshold.
    concentration_items = [p for p in priorities["priorities"] if p["type"] == "concentration"]
    assert any(item["security_name"] == "Nestle SA" for item in concentration_items)


def test_build_portfolio_priorities_single_portfolio():
    client, ref = first_client()
    view = build_client_view(client, ref)
    bundle = build_portfolio_priorities(view, view["portfolios"][0])
    assert bundle["portfolio_name"] == "Vorsorge Indiv"
    assert "top_risk_contributors" in bundle
    assert "performance" in bundle
