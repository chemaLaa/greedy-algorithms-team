from helpers import load_fixture_data


def test_security_lookup_resolves_known_id():
    _, _, ref = load_fixture_data()
    sec = ref.security(1001)
    assert sec is not None
    assert sec["Name"] == "Nestle SA"


def test_security_lookup_returns_none_for_unknown_id():
    _, _, ref = load_fixture_data()
    assert ref.security(999999) is None


def test_security_lookup_returns_none_for_none_id():
    _, _, ref = load_fixture_data()
    assert ref.security(None) is None


def test_to_saa_category_direct_translation():
    _, _, ref = load_fixture_data()
    # Fixture: Security 1001's AssetClassName "Equities Switzerland" pairs
    # with SAA_AssetClassName "Shares".
    assert ref.to_saa_category("AssetClass", "Equities Switzerland") == "Shares"


def test_to_saa_category_unknown_plain_name_returns_none():
    _, _, ref = load_fixture_data()
    assert ref.to_saa_category("AssetClass", "Some Unmapped Category") is None


def test_catch_all_is_none_when_ambiguous():
    # Fixture has 3 AssetClass pairs with no plain/SAA name overlap
    # (Equities Switzerland->Shares, Mixed Fund->Mixed, Bonds CHF
    # domestic->Bonds), so there are 3 candidate "never-a-plain-name" SAA
    # values — catch_all_saa_category must refuse to guess among them.
    _, _, ref = load_fixture_data()
    assert ref.catch_all_saa_category("AssetClass") is None


def test_catch_all_infers_unambiguous_bucket():
    # Standalone example (not the shared fixture): 3 currencies keep their
    # own name (identity mapping) and 1 doesn't appear as any plain name
    # at all — that one is unambiguously the catch-all, mirroring the real
    # dataset's CurrencyGroup "Andere" behavior.
    from data_layer import ReferenceIndex

    reference = {
        "Securities": [
            {"Id": 1, "CurrencyGroupName": "Euro", "SAA_CurrencyGroupName": "Euro"},
            {"Id": 2, "CurrencyGroupName": "Swiss francs", "SAA_CurrencyGroupName": "Swiss francs"},
            {"Id": 3, "CurrencyGroupName": "US-Dollar", "SAA_CurrencyGroupName": "US-Dollar"},
            {"Id": 4, "CurrencyGroupName": "British pound", "SAA_CurrencyGroupName": "Other"},
        ]
    }
    ref = ReferenceIndex(reference)
    assert ref.catch_all_saa_category("CurrencyGroup") == "Other"
    # And an id with no direct pair (e.g. an exotic currency only seen
    # inside a fund breakdown, never as a security's own currency) should
    # still resolve via that catch-all when the caller falls back to it.
    assert ref.to_saa_category("CurrencyGroup", "Norwegian Krone") is None


def test_fund_unbundling_grouped_by_fund_security_id():
    _, _, ref = load_fixture_data()
    rows = ref.fund_unbundling(2002)
    assert len(rows) == 2
    assert ref.fund_unbundling(999999) == []


def test_is_recommended():
    _, _, ref = load_fixture_data()
    assert ref.is_recommended(1001) is True
    assert ref.is_recommended(2002) is False
    assert ref.is_recommended(None) is False
