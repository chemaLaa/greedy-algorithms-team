from pathlib import Path

from data_layer import load_clients, load_reference, ReferenceIndex, build_client_view
from analysis_layer import build_client_priorities
from state import refresh_client_state
from enrichment.house_view import compare_portfolio_to_house_view
from synthesis.context_builder import build_briefing_context
from synthesis.briefing_generator import generate_briefing, BriefingGenerationError

clients = load_clients("data/core-case/portfolio-data/clients.json")
reference = load_reference("data/core-case/portfolio-data/reference.json")
ref = ReferenceIndex(reference)

# Persistent (not temp) state dir — running this script again later will
# show real "changed since last interaction" diffs instead of always
# reporting a first interaction.
state_dir = Path(".state_test")

# A deliberately varied mix: one already used before (CASE-002, has fund
# positions), one with several active violations (CASE-034), plus a
# couple of arbitrary others for spread.
client_refs_to_test = ["CASE-002", "CASE-034", "CASE-010", "CASE-020"]

for client_ref in client_refs_to_test:
    c = next((c for c in clients if c.get("ClientRef") == client_ref), None)
    if c is None:
        print(f"=== {client_ref}: not found, skipping ===\n")
        continue

    view = build_client_view(c, ref)
    bundles = build_client_priorities(view, ref)
    state_result = refresh_client_state(view, bundles, state_dir=state_dir)
    portfolio = view["portfolios"][0]
    pid = str(portfolio["PortfolioId"])
    house_view = compare_portfolio_to_house_view(portfolio)

    context = build_briefing_context(view, bundles[0], state_result["portfolios"][pid], house_view, [])

    print(f"{'=' * 70}")
    print(f"{client_ref} — {view['display_name']}")
    print(f"{'=' * 70}")

    try:
        briefing = generate_briefing(context)
    except BriefingGenerationError as e:
        print(f"FAILED: {e}\n")
        continue

    print()
    print("RECENT DEVELOPMENT:")
    print(briefing["recent_development"])
    print()
    print("HEALTH CHECK:")
    print(briefing["health_check"])
    print()
    print("OUTLOOK & ACTIONS:")
    print(briefing["outlook_and_actions"])
    print()
    print(f"(~{briefing['read_time_estimate_seconds']}s read)")
    print()
