from helpers import first_client
from data_layer import build_client_view
from analysis_layer import build_client_priorities
from synthesis.context_builder import build_briefing_context


def _view_and_bundle():
    client, ref = first_client()
    view = build_client_view(client, ref)
    bundles = build_client_priorities(view, ref)
    return view, bundles[0]


def test_client_section_populated():
    view, bundle = _view_and_bundle()
    context = build_briefing_context(view, bundle)
    assert context["client"]["name"] == "Anna Meier"
    assert context["client"]["risk_profile"] == "Balanced"


def test_client_section_handles_missing_risk_profile():
    view, bundle = _view_and_bundle()
    view = {**view, "risk_profile": None, "esg_profile": None}
    context = build_briefing_context(view, bundle)
    assert context["client"]["risk_profile"] is None
    assert context["client"]["esg_profile"] is None


def test_portfolio_section_matches_the_right_portfolio():
    view, bundle = _view_and_bundle()
    context = build_briefing_context(view, bundle)
    assert context["portfolio"]["portfolio_id"] == bundle["portfolio_id"]
    assert context["portfolio"]["portfolio_name"] == "Vorsorge Indiv"
    assert context["portfolio"]["value"] == 500000


def test_priorities_and_risk_contributors_passed_through():
    view, bundle = _view_and_bundle()
    context = build_briefing_context(view, bundle)
    assert context["priorities"] == bundle["priorities"]
    assert context["top_risk_contributors"] == bundle["top_risk_contributors"]


def test_change_section_uses_state_diff_when_provided():
    view, bundle = _view_and_bundle()
    fake_state_result = {
        "snapshot": {"portfolio_value": 500000},
        "diff": {"is_first_interaction": True, "violations_new": ["X"]},
    }
    context = build_briefing_context(view, bundle, state_result=fake_state_result)
    change = context["change_since_last_interaction"]
    assert change["source"] == "state_diff"
    assert change["is_first_interaction"] is True
    assert change["details"]["violations_new"] == ["X"]


def test_change_section_falls_back_to_note_proxy_without_state():
    view, bundle = _view_and_bundle()
    context = build_briefing_context(view, bundle, state_result=None)
    change = context["change_since_last_interaction"]
    assert change["source"] == "note_date_proxy"
    assert change["is_first_interaction"] is None
    assert change["details"] == bundle["change_since_last_interaction"]


def test_house_view_and_news_default_to_empty_lists():
    view, bundle = _view_and_bundle()
    context = build_briefing_context(view, bundle)
    assert context["house_view_alignment"] == []
    assert context["market_news"] == []


def test_house_view_and_news_pass_through_when_given():
    view, bundle = _view_and_bundle()
    house_view = [{"category": "Shares", "relative_position": "aligned"}]
    news = [{"title": "Test"}]
    context = build_briefing_context(view, bundle, house_view_alignment=house_view, news_articles=news)
    assert context["house_view_alignment"] == house_view
    assert context["market_news"] == news
    assert context["market_news_status"]["status"] == "ok"


def test_news_articles_empty_defaults_status_to_unavailable_not_fetch_failed():
    # Without a real news_bundle, the most that can honestly be claimed
    # from an empty list is "nothing came back" — never fabricate a
    # provider-failure claim this caller never actually reported.
    view, bundle = _view_and_bundle()
    context = build_briefing_context(view, bundle, news_articles=[])
    assert context["market_news_status"]["status"] == "unavailable"


def test_news_bundle_takes_precedence_and_carries_status_through():
    view, bundle = _view_and_bundle()
    news_bundle = {
        "status": "fetch_failed",
        "reasons": ["all_search_subjects_failed"],
        "articles": [],
    }
    context = build_briefing_context(view, bundle, news_bundle=news_bundle)
    assert context["market_news"] == []
    assert context["market_news_status"]["status"] == "fetch_failed"
    assert context["market_news_status"]["reasons"] == ["all_search_subjects_failed"]


def test_missing_portfolio_id_does_not_crash():
    view, bundle = _view_and_bundle()
    bad_bundle = {**bundle, "portfolio_id": 999999}  # no matching portfolio
    context = build_briefing_context(view, bad_bundle)
    assert context["portfolio"]["value"] is None


# --- attribution_caveat ---


def test_attribution_caveat_reflects_real_bundle_facts():
    view, bundle = _view_and_bundle()
    context = build_briefing_context(view, bundle)
    caveat = context["attribution_caveat"]
    assert caveat["liquidity_ratio"] == bundle["liquidity"]["liquidity_ratio"]
    assert caveat["has_holdings_based_drivers"] == bool(bundle["top_risk_contributors"])
    assert caveat["non_base_currency_exposure"] == bundle["concentrations"]["non_base_currency_exposure"]


def test_attribution_caveat_no_holdings_based_drivers_when_contributors_empty():
    view, bundle = _view_and_bundle()
    empty_bundle = {**bundle, "top_risk_contributors": []}
    context = build_briefing_context(view, empty_bundle)
    assert context["attribution_caveat"]["has_holdings_based_drivers"] is False


def test_attribution_caveat_handles_missing_liquidity_and_concentrations():
    view, bundle = _view_and_bundle()
    sparse_bundle = {k: v for k, v in bundle.items() if k not in ("liquidity", "concentrations")}
    context = build_briefing_context(view, sparse_bundle)
    caveat = context["attribution_caveat"]
    assert caveat["liquidity_ratio"] is None
    assert caveat["non_base_currency_exposure"] is None


# --- client_notes ---


def test_client_notes_surfaces_the_fixture_client_note():
    # The shared fixture (test_fixtures/clients.sample.json) already has a
    # real ClientNotes entry — confirms build_briefing_context() actually
    # surfaces note CONTENT, not just a date, for a client built through
    # the normal data_layer -> analysis_layer pipeline.
    view, bundle = _view_and_bundle()
    context = build_briefing_context(view, bundle)
    assert context["client_notes"] == [
        {"date": "2026-06-01T00:00:00Z", "text": "Client plans a property purchase next year."}
    ]


def test_client_notes_sorted_most_recent_first():
    view, bundle = _view_and_bundle()
    view_with_notes = {
        **view,
        "notes": [
            {"Note": "Oldest.", "CreatedByDateUTC": "2024-01-01T00:00:00"},
            {"Note": "Newest.", "CreatedByDateUTC": "2026-09-01T00:00:00"},
            {"Note": "Middle.", "CreatedByDateUTC": "2025-05-01T00:00:00"},
        ],
    }
    context = build_briefing_context(view_with_notes, bundle)
    texts = [n["text"] for n in context["client_notes"]]
    assert texts == ["Newest.", "Middle.", "Oldest."]


def test_client_notes_skips_entries_with_no_text():
    view, bundle = _view_and_bundle()
    view_with_notes = {
        **view,
        "notes": [
            {"Note": "", "CreatedByDateUTC": "2026-01-01T00:00:00"},
            {"CreatedByDateUTC": "2026-01-02T00:00:00"},  # missing "Note" entirely
            {"Note": "Real note.", "CreatedByDateUTC": "2026-01-03T00:00:00"},
        ],
    }
    context = build_briefing_context(view_with_notes, bundle)
    assert len(context["client_notes"]) == 1
    assert context["client_notes"][0]["text"] == "Real note."


def test_client_notes_capped_at_max():
    view, bundle = _view_and_bundle()
    view_with_notes = {
        **view,
        "notes": [
            {"Note": f"Note {i}", "CreatedByDateUTC": f"2026-01-{i + 1:02d}T00:00:00"} for i in range(10)
        ],
    }
    context = build_briefing_context(view_with_notes, bundle)
    from synthesis.context_builder import CLIENT_NOTES_MAX

    assert len(context["client_notes"]) == CLIENT_NOTES_MAX
    # And it kept the most recent ones, not an arbitrary slice.
    assert context["client_notes"][0]["text"] == "Note 9"
