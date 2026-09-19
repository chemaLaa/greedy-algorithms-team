from data_layer import load_clients, load_reference, ReferenceIndex, build_client_view
from analysis_layer import build_client_priorities
from state import refresh_client_state
from enrichment.house_view import compare_portfolio_to_house_view
from synthesis.context_builder import build_briefing_context
from synthesis.briefing_generator import generate_briefing, _default_client, build_prompt
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

# Make the raw API call ourselves, bypassing generate_briefing entirely,
# so we can inspect the FULL raw response object before any parsing.
client = _default_client()
print("Client base_url:", client.base_url)
print()

prompt = build_prompt(context)
response = client.messages.create(
    model="claude-sonnet-5",
    max_tokens=4096,
    system=prompt["system"],
    messages=prompt["messages"],
)

print("=== stop_reason ===")
print(response.stop_reason)
print()
print("=== model (as reported back by the API) ===")
print(response.model)
print()
print("=== usage ===")
print(response.usage)
print()
print("=== FULL raw text (repr, nothing truncated) ===")
for block in response.content:
    if getattr(block, "type", None) == "text":
        print(repr(block.text))