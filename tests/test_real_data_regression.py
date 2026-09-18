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
