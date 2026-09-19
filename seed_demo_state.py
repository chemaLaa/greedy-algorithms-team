"""
seed_demo_state.py
──────────────────
Plants a fake "previous briefing" snapshot for a demo client so that the
next call to POST /api/briefing produces a non-trivial "Since last
interaction" diff.

Which client?  The individual client with the most ranked priorities and
SAA deviations in the currently-loaded database — discovered automatically,
so this script works with any clients.json / reference.json pair.

Run once before the demo:

    python3 seed_demo_state.py

Then generate a briefing in the browser (without ?mock=1).
The "Since last interaction" section will show real, computed changes.

To reset to first-interaction state (empty diff on next call):

    python3 seed_demo_state.py --reset

To target a specific client by ID:

    python3 seed_demo_state.py --client 49388
"""
import json
import os
import sys
import copy
from datetime import datetime, timezone, timedelta
from pathlib import Path

CLIENTS_PATH   = os.environ.get("CLIENTS_PATH",   "data/core-case/portfolio-data/clients.json")
REFERENCE_PATH = os.environ.get("REFERENCE_PATH", "data/core-case/portfolio-data/reference.json")
STATE_DIR      = Path(".state")   # must match server.py's STATE_DIR


def find_best_client(clients, ref):
    """Return (client_view, bundle) for the individual with the most priorities."""
    from data_layer import build_client_view
    from analysis_layer import build_client_priorities

    best_score, best_view, best_bundle = -1, None, None
    for raw in clients:
        if raw.get("IsClientACompany"):
            continue   # prefer individuals for demo readability
        try:
            view    = build_client_view(raw, ref)
            bundles = build_client_priorities(view, ref)
        except Exception:
            continue
        for b in bundles:
            score = len(b.get("priorities") or []) * 2 + len(b.get("saa_target_deviations") or [])
            if score > best_score:
                best_score, best_view, best_bundle = score, view, b

    return best_view, best_bundle


def make_past_snapshot(bundle, portfolio, days_ago=30):
    """
    Build a snapshot that looks like it was taken `days_ago` days ago,
    with values slightly different from today so the diff has visible changes.
    """
    from state.snapshot import build_portfolio_snapshot

    snap = build_portfolio_snapshot(portfolio, bundle)

    # Back-date it
    snap["captured_at"] = (
        datetime.now(timezone.utc) - timedelta(days=days_ago)
    ).isoformat()

    # Tweak portfolio value so a value-change diff appears
    snap["portfolio_value"] = snap["portfolio_value"] * 1.037   # +3.7 %

    # Shift allocations so several dimension diffs cross the 0.5 pp threshold
    for dim, cats in snap.get("allocation", {}).items():
        keys = list(cats.keys())
        if len(keys) >= 2:
            # Move 7 pp from the largest category to the second-largest
            largest = max(keys, key=lambda k: cats[k])
            second  = sorted(keys, key=lambda k: cats[k])[-2]
            shift   = min(0.07, cats[largest] * 0.10)
            cats[largest] -= shift
            cats[second]  += shift

    # Drop the last violation so it shows up as "newly appeared"
    if snap.get("violations") and len(snap["violations"]) > 1:
        snap["violations"] = snap["violations"][:-1]

    # Swap out the last top-5 position so one shows as entered/exited
    if snap.get("top_positions") and len(snap["top_positions"]) >= 1:
        snap["top_positions"][-1] = {
            "SecurityId":   -1,
            "SecurityName": "Previous position (exited top 5)",
            "weight":       snap["top_positions"][-1]["weight"],
        }

    return snap


def seed(target_client_id=None):
    from data_layer import load_clients, load_reference, ReferenceIndex, build_client_view
    from analysis_layer import build_client_priorities

    clients = load_clients(CLIENTS_PATH)
    ref     = ReferenceIndex(load_reference(REFERENCE_PATH))

    if target_client_id:
        raw = next((c for c in clients if str(c.get("ClientId")) == target_client_id), None)
        if raw is None:
            print(f"ERROR: client {target_client_id!r} not found in {CLIENTS_PATH}", file=sys.stderr)
            sys.exit(1)
        view   = build_client_view(raw, ref)
        bundle = build_client_priorities(view, ref)[0]
    else:
        view, bundle = find_best_client(clients, ref)
        if view is None:
            print("ERROR: no suitable client found", file=sys.stderr)
            sys.exit(1)

    client_ref  = view["client_ref"]
    portfolio_id = str(bundle["portfolio_id"])
    portfolio   = next(
        (p for p in view["portfolios"] if str(p.get("PortfolioId")) == portfolio_id),
        None,
    )
    if portfolio is None:
        print(f"ERROR: portfolio {portfolio_id} not found", file=sys.stderr)
        sys.exit(1)

    past_snap = make_past_snapshot(bundle, portfolio)

    STATE_DIR.mkdir(parents=True, exist_ok=True)
    state_file = STATE_DIR / f"{client_ref}.json"
    state_file.write_text(json.dumps(
        {"snapshots": {portfolio_id: past_snap}, "events": []},
        indent=2,
    ))

    aum = portfolio.get("AssetsUnderManagementInDefaultCurrency", 0)
    print(f"Seeded {state_file}")
    print(f"Client : {view['display_name']}  (id={view['client_id']}, ref={client_ref})")
    print(f"Portfolio: {bundle['portfolio_name']}  (id={portfolio_id})")
    print(f"AUM    : CHF {aum:,.0f}")
    print(f"Priorities in current data: {len(bundle.get('priorities') or [])}")
    print()
    print("Expected diff on next briefing call:")
    print(f"  • Portfolio value: +3.7 % artificial increase reversed → appears as a drop")
    print(f"  • Several allocation dimensions shifted ≥ 7 pp")
    print(f"  • Last violation appears as newly active")
    print(f"  • One top-5 position entered, one exited")
    print()
    print("Re-run this script before each demo to restore the stale baseline.")


def reset(target_client_id=None):
    if target_client_id:
        from data_layer import load_clients, load_reference, ReferenceIndex, build_client_view
        clients = load_clients(CLIENTS_PATH)
        ref     = ReferenceIndex(load_reference(REFERENCE_PATH))
        raw     = next((c for c in clients if str(c.get("ClientId")) == target_client_id), None)
        if raw is None:
            print(f"ERROR: client {target_client_id!r} not found", file=sys.stderr)
            sys.exit(1)
        client_ref = build_client_view(raw, ref)["client_ref"]
        files = [STATE_DIR / f"{client_ref}.json"]
    else:
        files = list(STATE_DIR.glob("*.json"))

    if not files:
        print("No state files found.")
        return
    for f in files:
        if f.exists():
            f.unlink()
            print(f"Deleted {f}")
    print("Next briefing call will be a first-interaction baseline.")


if __name__ == "__main__":
    args = sys.argv[1:]
    client_arg = None
    if "--client" in args:
        idx = args.index("--client")
        client_arg = args[idx + 1] if idx + 1 < len(args) else None

    if "--reset" in args:
        reset(client_arg)
    else:
        seed(client_arg)
