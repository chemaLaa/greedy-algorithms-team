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


# --- client_interests ---


def test_client_interests_surfaces_the_fixture_client_tags():
    # The shared fixture already has real Tags[] entries — confirms
    # client_view["tags"] (previously computed and never read by
    # anything) now actually reaches the BriefingContext.
    view, bundle = _view_and_bundle()
    context = build_briefing_context(view, bundle)
    assert {"category": "Switzerland", "tag_type": "Region"} in context["client_interests"]
    assert {"category": "Health Care", "tag_type": "Industry"} in context["client_interests"]


def test_client_interests_empty_when_no_tags():
    view, bundle = _view_and_bundle()
    view_without_tags = {**view, "tags": []}
    context = build_briefing_context(view_without_tags, bundle)
    assert context["client_interests"] == []


def test_client_interests_skips_tags_with_no_name():
    view, bundle = _view_and_bundle()
    view_with_tags = {**view, "tags": [{"TagName": None, "TagTypeName": "Region"}]}
    context = build_briefing_context(view_with_tags, bundle)
    assert context["client_interests"] == []


# --- current_risk_return ---


def test_current_risk_return_surfaces_the_bundles_expected_return():
    # The fixture bundle already has a real current_risk_return snapshot
    # (analysis_layer.performance.current_risk_return_snapshot()) that
    # was previously computed and dropped — never read by anything.
    view, bundle = _view_and_bundle()
    context = build_briefing_context(view, bundle)
    crr = context["current_risk_return"]
    assert crr["status"] == bundle["current_risk_return"]["status"]
    assert crr["expected_return"] == bundle["current_risk_return"]["expected_return"]
    assert crr["volatility"] == bundle["current_risk_return"]["volatility"]


def test_current_risk_return_missing_from_bundle_reports_unavailable_status():
    view, bundle = _view_and_bundle()
    sparse_bundle = {k: v for k, v in bundle.items() if k != "current_risk_return"}
    context = build_briefing_context(view, sparse_bundle)
    crr = context["current_risk_return"]
    assert crr["status"] is None
    assert crr["expected_return"] is None


# --- sources ---


def test_sources_includes_priority_facts_with_matching_fact_id():
    # The shared fixture's bundle has real saa_breach, violation, and
    # single_position_concentration priorities with fact_ids.
    view, bundle = _view_and_bundle()
    context = build_briefing_context(view, bundle)
    priority_sources = [s for s in context["sources"] if s["type"] == "priority_fact"]
    assert len(priority_sources) == len(bundle["priorities"])

    saa_source = next(s for s in priority_sources if s["fact_id"] == "9001:saa_breach:AssetClass:Bonds:0")
    assert "Bonds" in saa_source["label"]
    assert "SAA deviation" in saa_source["label"]

    concentration_source = next(
        s for s in priority_sources if s["fact_id"] == "9001:single_position_concentration:1001"
    )
    # Cleaned, not the raw "Namen-Aktie..." style name.
    assert "Nestle SA" in concentration_source["label"]

    assert all(s["url"] is None for s in priority_sources)


def test_sources_includes_risk_contributors():
    view, bundle = _view_and_bundle()
    bundle_with_contributor = {
        **bundle,
        "top_risk_contributors": [{"SecurityName": "Namen-Aktie Nestle SA", "share_of_portfolio_volatility": 0.3}],
    }
    context = build_briefing_context(view, bundle_with_contributor)
    contributor_sources = [s for s in context["sources"] if s["type"] == "risk_contributor"]
    assert len(contributor_sources) == 1
    assert "Nestle SA" in contributor_sources[0]["label"]
    assert "Namen-Aktie" not in contributor_sources[0]["label"]


def test_sources_includes_house_view_entry_with_as_of_date():
    view, bundle = _view_and_bundle()
    house_view = [
        {"category": "Shares", "relative_position": "aligned", "as_of": "2026-09-01", "source": "mock", "is_mock": True}
    ]
    context = build_briefing_context(view, bundle, house_view_alignment=house_view)
    house_view_sources = [s for s in context["sources"] if s["type"] == "house_view"]
    assert len(house_view_sources) == 1
    assert house_view_sources[0]["date"] == "2026-09-01"
    assert "mock" in house_view_sources[0]["label"].lower()


def test_sources_includes_news_articles_with_real_links():
    view, bundle = _view_and_bundle()
    news_bundle = {
        "status": "ok",
        "reasons": [],
        "articles": [
            {"title": "Nestle earnings beat forecasts", "publisher": "Reuters", "link": "http://example.com/a", "published_at": "2026-09-01"}
        ],
    }
    context = build_briefing_context(view, bundle, news_bundle=news_bundle)
    news_sources = [s for s in context["sources"] if s["type"] == "news_article"]
    assert len(news_sources) == 1
    assert news_sources[0]["url"] == "http://example.com/a"
    assert "Nestle earnings beat forecasts" in news_sources[0]["label"]
    assert "Reuters" in news_sources[0]["label"]


def test_sources_includes_client_notes_and_interests():
    view, bundle = _view_and_bundle()
    context = build_briefing_context(view, bundle)
    note_sources = [s for s in context["sources"] if s["type"] == "client_note"]
    interest_sources = [s for s in context["sources"] if s["type"] == "client_interest_tag"]
    assert len(note_sources) == len(context["client_notes"]) > 0
    assert "property purchase" in note_sources[0]["label"]
    assert len(interest_sources) == len(context["client_interests"]) > 0


def test_sources_includes_expected_return_when_available():
    view, bundle = _view_and_bundle()
    context = build_briefing_context(view, bundle)
    expected_return_sources = [s for s in context["sources"] if s["type"] == "expected_return"]
    assert len(expected_return_sources) == 1
    assert "forward-looking" in expected_return_sources[0]["label"]


def test_sources_excludes_expected_return_when_unavailable():
    view, bundle = _view_and_bundle()
    bundle_without_expected_return = {
        **bundle,
        "current_risk_return": {"status": "unavailable", "reasons": ["current_risk_return_metrics_missing"], "expected_return": None},
    }
    context = build_briefing_context(view, bundle_without_expected_return)
    assert not [s for s in context["sources"] if s["type"] == "expected_return"]


def test_sources_empty_when_nothing_to_cite():
    view, bundle = _view_and_bundle()
    minimal_bundle = {
        **bundle,
        "priorities": [],
        "top_risk_contributors": [],
        "concentrations": {},
        "current_risk_return": {"status": "unavailable", "reasons": [], "expected_return": None},
    }
    minimal_view = {**view, "notes": [], "tags": []}
    context = build_briefing_context(minimal_view, minimal_bundle)
    assert context["sources"] == []
