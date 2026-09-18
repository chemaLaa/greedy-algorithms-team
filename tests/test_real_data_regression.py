"""
Regression tests against the real UnRiskOmega dataset. These encode
everything we checked by hand during development (all 47 clients build
without error, every join resolves, no stray SAA categories, the specific
CASE-002 fund-translation numbers) so a future change can't silently
reintroduce a bug we already found and fixed once.

Point UNRISKOMEGA_DATA_DIR at a folder containing clients.json and
reference.json if your layout differs (defaults to this repo's own
data/core-case/portfolio-data/). Tests in this file are skipped — not
failed — if the files aren't found there, since the real data isn't
necessarily checked into every clone of the repo.
"""
import os

from helpers import load_fixture_data  # noqa: F401 (keeps helpers importable first)
from data_layer import load_clients, load_reference, ReferenceIndex, build_client_view

# Default assumes this file lives at <repo>/tests/test_real_data_regression.py
# and the case data lives at <repo>/data/core-case/portfolio-data/.
_REPO_ROOT = os.path.join(os.path.dirname(__file__), "..")
_DEFAULT_DATA_DIR = os.path.join(_REPO_ROOT, "data", "core-case", "portfolio-data")

DATA_DIR = os.environ.get("UNRISKOMEGA_DATA_DIR", _DEFAULT_DATA_DIR)
CLIENTS_PATH = os.path.join(DATA_DIR, "clients.json")
REFERENCE_PATH = os.path.join(DATA_DIR, "reference.json")

REAL_DATA_AVAILABLE = os.path.exists(CLIENTS_PATH) and os.path.exists(REFERENCE_PATH)
SKIP_REASON = f"real data not found at {DATA_DIR} (set UNRISKOMEGA_DATA_DIR)"


def _load_real():
    clients = load_clients(CLIENTS_PATH)
    reference = load_reference(REFERENCE_PATH)
    ref = ReferenceIndex(reference)
    return clients, reference, ref


def test_all_47_clients_build_without_error():
    if not REAL_DATA_AVAILABLE:
        print(f"SKIPPED: {SKIP_REASON}")
        return
    clients, _, ref = _load_real()
    assert len(clients) == 47
    for c in clients:
        build_client_view(c, ref)  # raises on failure


def test_no_stray_saa_categories_across_all_clients():
    if not REAL_DATA_AVAILABLE:
        print(f"SKIPPED: {SKIP_REASON}")
        return
    clients, _, ref = _load_real()

    valid_by_dimension = {}
    for saa in ref.strategic_asset_allocations.values():
        for m in saa.get("Mappings") or []:
            valid_by_dimension.setdefault(m["Dimension"], set()).add(m["Category"])

    for c in clients:
        view = build_client_view(c, ref)
        for p in view["portfolios"]:
            for dimension, rows in p["saa_deviations"].items():
                valid = valid_by_dimension.get(dimension, set())
                for row in rows:
                    # A category should either be a known SAA target bucket,
                    # or have zero actual holding (a target-only row) — it
                    # should never be a leftover fine-grained name that
                    # failed to translate.
                    assert row["category"] in valid or row["actual"] == 0, (
                        f"{c.get('ClientRef')}: stray category "
                        f"{row['category']!r} in {dimension}"
                    )


def test_case_002_fund_translation_matches_known_good_values():
    if not REAL_DATA_AVAILABLE:
        print(f"SKIPPED: {SKIP_REASON}")
        return
    clients, _, ref = _load_real()
    client = next(c for c in clients if c.get("ClientRef") == "CASE-002")
    view = build_client_view(client, ref)
    rows = {r["category"]: r for r in view["portfolios"][0]["saa_deviations"]["AssetClass"]}

    # Known-good values from manual verification: Shares landed at ~52%
    # (on target), not the pre-fix bug value of 0%.
    assert abs(rows["Shares"]["actual"] - 0.520) < 0.001
    assert rows["Shares"]["breaches_min"] is False


def test_case_008_orphaned_proposal_does_not_crash():
    if not REAL_DATA_AVAILABLE:
        print(f"SKIPPED: {SKIP_REASON}")
        return
    clients, _, ref = _load_real()
    client = next(c for c in clients if c.get("ClientRef") == "CASE-008")
    # Known data quirk: this client has a proposal pointing at a
    # PortfolioId that isn't one of their own. Should not raise.
    build_client_view(client, ref)


def test_analysis_layer_runs_clean_across_all_47_clients():
    if not REAL_DATA_AVAILABLE:
        print(f"SKIPPED: {SKIP_REASON}")
        return
    from analysis_layer import build_client_priorities

    clients, _, ref = _load_real()
    for c in clients:
        view = build_client_view(c, ref)
        build_client_priorities(view, ref)  # raises on failure


def test_violation_description_fallback_covers_known_blank_rules():
    if not REAL_DATA_AVAILABLE:
        print(f"SKIPPED: {SKIP_REASON}")
        return
    from analysis_layer import build_client_priorities

    clients, _, ref = _load_real()
    for c in clients:
        view = build_client_view(c, ref)
        for bundle in build_client_priorities(view, ref):
            for item in bundle["priorities"]:
                if item["type"] == "violation":
                    # Known gap: 2 of 54 SuitabilityRules have an empty
                    # Description everywhere in the source data — the
                    # RuleCode fallback in prioritize.py must cover it, so
                    # no violation should ever surface with a blank
                    # description.
                    assert item["description"], (
                        f"{c.get('ClientRef')}: blank violation description "
                        f"for rule_code={item['rule_code']!r}"
                    )


def test_state_layer_runs_clean_across_all_47_clients_twice():
    if not REAL_DATA_AVAILABLE:
        print(f"SKIPPED: {SKIP_REASON}")
        return
    import tempfile
    from pathlib import Path

    from analysis_layer import build_client_priorities
    from state import refresh_client_state

    clients, _, ref = _load_real()
    state_dir = Path(tempfile.mkdtemp())
    for c in clients:
        view = build_client_view(c, ref)
        bundles = build_client_priorities(view, ref)
        first = refresh_client_state(view, bundles, state_dir=state_dir)
        second = refresh_client_state(view, bundles, state_dir=state_dir)

        for portfolio_id, entry in first["portfolios"].items():
            assert entry["diff"]["is_first_interaction"] is True
        for portfolio_id, entry in second["portfolios"].items():
            # Same data both times — a repeat call must show no false changes.
            assert entry["diff"]["is_first_interaction"] is False
            assert entry["diff"]["violations_new"] == []
            assert entry["diff"]["violations_resolved"] == []


def test_state_diff_detects_a_real_manufactured_change():
    if not REAL_DATA_AVAILABLE:
        print(f"SKIPPED: {SKIP_REASON}")
        return
    import copy
    import tempfile
    from pathlib import Path

    from analysis_layer import build_client_priorities
    from state import refresh_client_state

    clients, _, ref = _load_real()
    state_dir = Path(tempfile.mkdtemp())

    client = next(c for c in clients if c.get("ClientRef") == "CASE-002")
    view = build_client_view(client, ref)
    bundles = build_client_priorities(view, ref)
    refresh_client_state(view, bundles, state_dir=state_dir)

    # Manufacture a real change: resolve one violation via an override,
    # bump the portfolio value +8% — mirrors the manual check done during
    # development.
    client2 = copy.deepcopy(client)
    resolved_code = client2["SuitabilityViolations"][0]["RuleCode"]
    client2["IndividualRuleOverrides"] = (client2.get("IndividualRuleOverrides") or []) + [
        {"RuleCode": resolved_code, "RuleDescription": "test"}
    ]
    client2["Portfolios"][0]["AssetsUnderManagementInDefaultCurrency"] *= 1.08

    view2 = build_client_view(client2, ref)
    bundles2 = build_client_priorities(view2, ref)
    result2 = refresh_client_state(view2, bundles2, state_dir=state_dir)

    portfolio_id = str(view2["portfolios"][0]["PortfolioId"])
    diff = result2["portfolios"][portfolio_id]["diff"]
    assert resolved_code in diff["violations_resolved"]
    assert abs(diff["portfolio_value_change"]["change_pct"] - 0.08) < 1e-6


def test_security_name_cleaner_coverage_on_real_data():
    if not REAL_DATA_AVAILABLE:
        print(f"SKIPPED: {SKIP_REASON}")
        return
    from enrichment.market_news import clean_security_name

    _, reference, _ = _load_real()
    names = [s["Name"] for s in reference["Securities"]]

    unchanged = [n for n in names if clean_security_name(n) == n and " - " not in n]
    coverage = 1 - (len(unchanged) / len(names))

    # Known-good baseline from development: ~95.8% of real security names
    # get meaningfully cleaned. A regression below 90% would mean a
    # naming pattern the dataset actually uses broke silently.
    assert coverage >= 0.90, (
        f"security name cleaner coverage dropped to {coverage:.1%} "
        f"(expected >= 90%) — {len(unchanged)} names now pass through unchanged"
    )

    # Never crashes, never returns an empty string for a non-empty input.
    for n in names:
        cleaned = clean_security_name(n)
        assert cleaned.strip() != ""


def test_house_view_comparison_runs_clean_across_all_47_clients():
    if not REAL_DATA_AVAILABLE:
        print(f"SKIPPED: {SKIP_REASON}")
        return
    from enrichment.house_view import compare_portfolio_to_house_view

    clients, _, ref = _load_real()
    seen_positions = set()
    for c in clients:
        view = build_client_view(c, ref)
        for portfolio in view["portfolios"]:
            result = compare_portfolio_to_house_view(portfolio)
            for item in result:
                seen_positions.add(item["relative_position"])

    # All four outcomes should genuinely occur somewhere across 47 real
    # clients — if only one or two ever show up, the comparison logic is
    # probably not discriminating correctly.
    assert seen_positions == {"aligned", "underexposed", "overexposed", "not_applicable"}
