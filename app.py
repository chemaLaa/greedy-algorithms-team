"""
Simplest possible demo UI for the UnRiskOmega briefing assistant — one
Streamlit app that calls the pipeline directly in-process. No API layer,
no separate frontend build, no CORS — just Python calling the modules
already built and tested.

Run: streamlit run app.py

This is a starting point, not a visual match to UnRiskOmega's actual
screenshots yet — once those are available, the styling here (or a
follow-up FastAPI + HTML version) can be adjusted to match.
"""
from pathlib import Path

import streamlit as st

from data_layer import ReferenceIndex, build_client_view, load_clients, load_reference
from analysis_layer import build_client_priorities
from state import refresh_client_state
from enrichment.house_view import compare_portfolio_to_house_view
from enrichment.market_news import YahooFinanceNewsProvider, fetch_relevant_news_bundle, relevant_search_terms
from synthesis.briefing_generator import BriefingGenerationError, generate_briefing
from synthesis.context_builder import build_briefing_context

DEFAULT_CLIENTS_PATH = "data/core-case/portfolio-data/clients.json"
DEFAULT_REFERENCE_PATH = "data/core-case/portfolio-data/reference.json"
STATE_DIR = Path(".state")

st.set_page_config(page_title="URO Advisor Pro — Briefing Assistant", layout="wide")


@st.cache_resource
def load_reference_index(reference_path: str) -> ReferenceIndex:
    reference = load_reference(reference_path)
    return ReferenceIndex(reference)


def _client_label(client: dict) -> str:
    """
    Matches data_layer.flatten's own display-name fallback logic: company
    clients don't have FirstName/LastName at all, so falling back to
    those blindly produces an empty, dash-trailing label. Checked
    against real data — 4 of 47 clients in the current dataset are
    companies.
    """
    client_ref = client.get("ClientRef", "Unknown")
    if client.get("IsClientACompany"):
        name = client.get("Company") or client_ref
    else:
        name = f"{(client.get('FirstName') or '')} {(client.get('LastName') or '')}".strip() or client_ref
    return f"{client_ref} — {name}"


st.title("URO Advisor Pro — AI Briefing Assistant")

with st.sidebar:
    st.header("Client data")
    uploaded = st.file_uploader(
        "Upload a new clients.json (optional — defaults to the case dataset)", type="json"
    )
    if uploaded is not None:
        clients = load_clients(uploaded)
    else:
        clients = load_clients(DEFAULT_CLIENTS_PATH)

    ref = load_reference_index(DEFAULT_REFERENCE_PATH)

    client_options = {_client_label(c): c for c in clients}
    selected_label = st.selectbox("Select client", list(client_options.keys()))
    selected_client = client_options[selected_label]

view = build_client_view(selected_client, ref)
portfolio = view["portfolios"][0]

col1, col2, col3 = st.columns(3)
col1.metric("Client", view["display_name"])
value = portfolio.get("AssetsUnderManagementInDefaultCurrency")
currency = view.get("reporting_currency", "")
col2.metric("Portfolio value", f"{value:,.0f} {currency}" if value is not None else "—")
risk_profile = view.get("risk_profile")
col3.metric("Risk profile", risk_profile["Name"] if risk_profile else "—")

bundles = build_client_priorities(view, ref)
bundle = bundles[0]

st.subheader("Active priorities")
if bundle["priorities"]:
    for item in bundle["priorities"]:
        if item["type"] == "violation":
            st.warning(f"[{item['severity']}] {item['description']}")
        elif item["type"] == "saa_breach":
            direction = "below" if item["breach"] == "min" else "above"
            st.info(
                f"{item['category']} ({item['dimension']}): {item['actual']:.1%} vs. "
                f"target {item['target']:.1%} — {direction} range"
            )
        elif item["type"] == "single_position_concentration":
            st.warning(f"{item['security_name']} — {item['weight']:.1%} of portfolio")
else:
    st.success("No active issues flagged.")

st.divider()

if st.button("🔔 Generate Briefing", type="primary"):
    with st.spinner("Generating briefing..."):
        state_result = refresh_client_state(view, bundles, state_dir=STATE_DIR)
        portfolio_id = str(portfolio["PortfolioId"])
        house_view = compare_portfolio_to_house_view(portfolio)

        terms = relevant_search_terms(portfolio, bundle, ref=ref)
        news_bundle = fetch_relevant_news_bundle(terms, YahooFinanceNewsProvider())
        if news_bundle["status"] == "fetch_failed":
            st.warning("Market news search failed (network/provider error) — briefing will note this rather than claim no news exists.")

        context = build_briefing_context(
            view, bundle, state_result["portfolios"][portfolio_id], house_view, news_bundle=news_bundle
        )

        try:
            briefing = generate_briefing(context)
        except BriefingGenerationError as e:
            st.error(f"Briefing generation failed: {e}")
            st.stop()

    st.success(f"Briefing ready — ~{briefing['read_time_estimate_seconds']}s read")

    st.markdown("### 📊 Recent Development")
    st.write(briefing["recent_development"])

    st.markdown("### ⚠️ Health Check")
    st.write(briefing["health_check"])

    st.markdown("### 🎯 Outlook & Actions")
    st.write(briefing["outlook_and_actions"])
