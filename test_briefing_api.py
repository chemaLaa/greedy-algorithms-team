"""
Smoke-test the Anthropic API call in synthesis/briefing_generator.py directly.

Usage:
    python test_briefing_api.py                  # uses first client in clients.json
    python test_briefing_api.py --client CASE-002

Requires:
    pip install anthropic certifi
    export ANTHROPIC_API_KEY=sk-ant-...
"""
import argparse
import sys
import time
from pathlib import Path

CLIENTS_PATH = "data/core-case/portfolio-data/clients.json"
REFERENCE_PATH = "data/core-case/portfolio-data/reference.json"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--client", metavar="CASE-xxx", default=None,
                        help="ClientRef to use (e.g. CASE-002); defaults to first client")
    args = parser.parse_args()

    # -- data layer --
    from data_layer import load_clients, load_reference, ReferenceIndex, build_client_view
    from analysis_layer import build_client_priorities
    from synthesis.context_builder import build_briefing_context
    from synthesis.briefing_generator import generate_briefing, BriefingGenerationError

    clients = load_clients(CLIENTS_PATH)
    if not clients:
        print("ERROR: clients.json is empty", file=sys.stderr)
        sys.exit(1)

    if args.client:
        client = next((c for c in clients if c.get("ClientRef") == args.client), None)
        if client is None:
            available = [c.get("ClientRef") for c in clients]
            print(f"ERROR: client '{args.client}' not found. Available: {available}", file=sys.stderr)
            sys.exit(1)
    else:
        client = clients[0]

    ref = ReferenceIndex(load_reference(REFERENCE_PATH))
    client_view = build_client_view(client, ref)
    bundles = build_client_priorities(client_view, ref)
    bundle = bundles[0]

    context = build_briefing_context(client_view, bundle)

    print(f"Client:    {client_view.get('display_name')} ({client.get('ClientRef')})")
    print(f"Portfolio: {bundle['portfolio_id']} — {bundle['portfolio_name']}")
    print(f"Priorities found: {len(bundle['priorities'])}")
    print("-" * 60)

    # -- API call --
    t_start = time.monotonic()
    print(f"[{_ts(t_start)}] Starting API call...")

    try:
        briefing = generate_briefing(context)
    except BriefingGenerationError as e:
        elapsed = time.monotonic() - t_start
        print(f"\nERROR after {elapsed:.1f}s: {e}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        elapsed = time.monotonic() - t_start
        print(f"\nInterrupted after {elapsed:.1f}s", file=sys.stderr)
        sys.exit(1)

    t_end = time.monotonic()
    elapsed = t_end - t_start
    print(f"[{_ts(t_start, offset=elapsed)}] Done — total {elapsed:.1f}s")
    print("=" * 60)

    print(f"Read time estimate: ~{briefing['read_time_estimate_seconds']}s\n")
    print("--- Recent Development ---")
    print(briefing["recent_development"])
    print("\n--- Health Check ---")
    print(briefing["health_check"])
    print("\n--- Outlook & Actions ---")
    print(briefing["outlook_and_actions"])
    print("\n--- Raw model response ---")
    print(briefing["raw_model_response"])


def _ts(t_start, offset=0.0):
    """Seconds-since-start label for log lines."""
    return f"+{offset:.1f}s"


if __name__ == "__main__":
    main()
