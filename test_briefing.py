from data_layer import load_clients, load_reference, ReferenceIndex, build_client_view
from analysis_layer import build_client_priorities
from state import refresh_client_state
from enrichment.house_view import compare_portfolio_to_house_view
from synthesis.context_builder import build_briefing_context
from synthesis.briefing_generator import generate_briefing
import tempfile
from pathlib import Path

clients = load_clients("data/core-case/portfolio-data/clients.json")
reference = load_reference("data/core-case/portfolio-data/reference.json")
ref = ReferenceIndex(reference)

c = clients[5]
view = build_client_view(c, ref)
bundles = build_client_priorities(view, ref)
state_dir = Path(tempfile.mkdtemp())
state_result = refresh_client_state(view, bundles, state_dir=state_dir)
portfolio = view["portfolios"][0]
pid = str(portfolio["PortfolioId"])
house_view = compare_portfolio_to_house_view(portfolio)

context = build_briefing_context(view, bundles[0], state_result["portfolios"][pid], house_view, [])
briefing = generate_briefing(context)
print(briefing["recent_development"])
print()
print(briefing["health_check"])
print()
print(briefing["outlook_and_actions"])
print()
print(f"~{briefing['read_time_estimate_seconds']}s read")