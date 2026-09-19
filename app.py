"""
Demo UI for the UnRiskOmega briefing assistant, styled to sit inside the
mocked URO Advisor Pro interface rather than as a bare upload-a-file form.

Two views, matching the two real screens the briefing feature would live
across (see data/core-case/GUI-screenshots/):
  1. Kundenberater-Dashboard — a client list (Client_Advisor_DB.png), with
     a warnings/violations count per row computed by the SAME analysis
     pipeline the briefing itself uses, and a "Generate Briefing" entry
     point per client. This is the "clear entry point" the case brief
     asks for — not a sidebar dropdown.
  2. Client detail — a header bar in the style of Client_DB.png, the
     "Active priorities" section (now defensive against None fields and
     unknown priority types — see _render_priority), and the briefing
     generation flow itself.

Header color (#5499E4) sampled directly from Client_Advisor_DB.png's top
bar; this is a demo restyle, not a pixel-perfect clone of a real Angular/
React enterprise app — the goal is "clearly belongs in this interface",
not a frontend rebuild.

Run: streamlit run app.py
"""
from pathlib import Path

import pandas as pd
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

URO_BLUE = "#5499E4"
SEVERITY_RED = "#D0342C"
SEVERITY_AMBER = "#E8A33D"

st.set_page_config(page_title="URO Advisor Pro — Briefing Assistant", layout="wide", page_icon="🔔")

st.markdown(
    f"""
    <style>
    .block-container {{ padding-top: 1rem; }}
    .uro-topbar {{
        background: {URO_BLUE};
        color: white;
        padding: 0.7rem 1.4rem;
        margin: -1rem -1rem 1.2rem -1rem;
        display: flex;
        align-items: center;
        justify-content: space-between;
        font-family: -apple-system, "Segoe UI", sans-serif;
    }}
    .uro-topbar .brand {{ font-size: 1.25rem; font-weight: 700; letter-spacing: 0.03em; }}
    .uro-topbar .user {{ font-size: 0.9rem; opacity: 0.92; }}
    .uro-client-header {{
        background: #f2f2f2;
        border-bottom: 1px solid #ddd;
        padding: 0.7rem 1.2rem;
        margin: -0.5rem -1rem 1rem -1rem;
        font-family: -apple-system, "Segoe UI", sans-serif;
    }}
    .uro-client-header .name {{ font-size: 1.1rem; font-weight: 700; }}
    .uro-client-header .meta {{ font-size: 0.85rem; color: #555; margin-top: 0.15rem; }}
    </style>
    """,
    unsafe_allow_html=True,
)


@st.cache_resource
def load_reference_index(reference_path: str) -> ReferenceIndex:
    reference = load_reference(reference_path)
    return ReferenceIndex(reference)


def _display_name(client: dict) -> str:
    """
    Matches data_layer.flatten's own display-name fallback logic: company
    clients don't have FirstName/LastName at all, so falling back to
    those blindly produces an empty, dash-trailing label. Checked
    against real data — 4 of 47 clients in the current dataset are
    companies.
    """
    client_ref = client.get("ClientRef", "Unknown")
    if client.get("IsClientACompany"):
        return client.get("Company") or client_ref
    name = f"{(client.get('FirstName') or '')} {(client.get('LastName') or '')}".strip()
    return name or client_ref


@st.cache_data(show_spinner="Loading client overview...")
def _client_summary_table(_ref: ReferenceIndex, clients: list[dict]) -> pd.DataFrame:
    """
    One row per client for the dashboard list — counts computed via the
    SAME analysis_layer pipeline the briefing itself uses (build_client_priorities),
    so a "2 warnings" badge here can never drift out of sync with what
    "Active priorities" actually shows once you drill into that client.
    `_ref` is prefixed with an underscore so Streamlit's cache doesn't try
    (and fail) to hash a ReferenceIndex object.
    """
    rows = []
    for client in clients:
        view = build_client_view(client, _ref)
        if not view["portfolios"]:
            continue
        bundle = build_client_priorities(view, _ref)[0]
        priorities = bundle["priorities"]
        violations = sum(1 for p in priorities if p["type"] == "violation" and p.get("severity") == "Error")
        warnings = len(priorities) - violations

        portfolio = view["portfolios"][0]
        rows.append(
            {
                "Client Ref": client.get("ClientRef"),
                "Name": _display_name(client),
                "AUM": portfolio.get("AssetsUnderManagementInDefaultCurrency"),
                "Currency": view.get("reporting_currency") or "",
                "Risk Profile": (view.get("risk_profile") or {}).get("Name") or "—",
                "Violations": violations,
                "Warnings": warnings,
            }
        )
    return pd.DataFrame(rows)


def _pct(value) -> str:
    return f"{value:.1%}" if isinstance(value, (int, float)) else "n/a"


def _render_priority(item: dict) -> None:
    """
    Renders one priorities-bundle item defensively: every field is read
    with .get() and formatted through _pct() rather than an f-string
    ':.1%' spec, which raises TypeError outright on a None value (the
    original bug — a saa_breach row can legitimately have no `target`
    when its SAA mapping sets Min/Max without a Target). Every known
    priority `type` is handled, and an unrecognized one still renders
    (generically) rather than silently vanishing from the list.
    """
    ptype = item.get("type")
    severity = item.get("severity") or "Info"

    if ptype == "violation":
        st.error(f"🔴 **[{severity}]** {item.get('description') or item.get('rule_code') or 'Unspecified violation'}")
    elif ptype == "saa_breach":
        direction = "below" if item.get("breach") == "min" else "above"
        st.warning(
            f"🟡 **{item.get('category', 'Unknown category')}** ({item.get('dimension', '—')}): "
            f"{_pct(item.get('actual'))} vs. target {_pct(item.get('target'))} — {direction} allowed range"
        )
    elif ptype == "single_position_concentration":
        st.warning(f"🟡 **{item.get('security_name') or 'Unknown position'}** — {_pct(item.get('weight'))} of portfolio")
    elif ptype == "high_liquidity":
        st.info(f"ℹ️ Portfolio liquidity is **{_pct(item.get('liquidity_ratio'))}** of AUM — may warrant discussion.")
    else:
        st.info(f"ℹ️ **[{severity}]** {ptype or 'unclassified item'}")


def _render_topbar() -> None:
    st.markdown(
        """
        <div class="uro-topbar">
          <div class="brand">◆ UNRISKOMEGA</div>
          <div class="user">👤 Hans Muster</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _load_clients_and_ref():
    with st.sidebar:
        st.header("Client data")
        uploaded = st.file_uploader(
            "Upload a new clients.json (optional — defaults to the case dataset)", type="json"
        )
        clients = load_clients(uploaded) if uploaded is not None else load_clients(DEFAULT_CLIENTS_PATH)
    ref = load_reference_index(DEFAULT_REFERENCE_PATH)
    return clients, ref


def render_client_list(clients: list[dict], ref: ReferenceIndex) -> None:
    _render_topbar()
    st.subheader("Kundenberater-Dashboard")

    table = _client_summary_table(ref, clients)
    total_violations = int(table["Violations"].sum()) if not table.empty else 0
    total_warnings = int(table["Warnings"].sum()) if not table.empty else 0

    col1, col2, col3 = st.columns(3)
    col1.metric("Clients", len(table))
    col2.metric("Active violations", total_violations)
    col3.metric("Warnings", total_warnings)

    st.caption("Select a client row to open their briefing entry point.")
    event = st.dataframe(
        table,
        use_container_width=True,
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row",
        column_config={
            "AUM": st.column_config.NumberColumn(format="%d"),
            "Violations": st.column_config.NumberColumn(),
            "Warnings": st.column_config.NumberColumn(),
        },
    )

    selected_rows = event.selection.rows if event.selection else []
    if selected_rows:
        st.session_state["selected_client_ref"] = table.iloc[selected_rows[0]]["Client Ref"]
        st.rerun()


def render_client_detail(clients: list[dict], ref: ReferenceIndex, client_ref: str) -> None:
    _render_topbar()

    if st.button("← Back to client list"):
        del st.session_state["selected_client_ref"]
        st.rerun()

    client = next((c for c in clients if c.get("ClientRef") == client_ref), None)
    if client is None:
        st.error(f"Client '{client_ref}' not found in the currently loaded dataset.")
        return

    view = build_client_view(client, ref)
    if not view["portfolios"]:
        st.warning(f"{_display_name(client)} ({client_ref}) has no portfolios in this dataset.")
        return
    portfolio = view["portfolios"][0]

    risk_profile = view.get("risk_profile")
    value = portfolio.get("AssetsUnderManagementInDefaultCurrency")
    currency = view.get("reporting_currency") or ""
    value_str = f"{value:,.0f} {currency}" if value is not None else "—"

    st.markdown(
        f"""
        <div class="uro-client-header">
          <div class="name">{_display_name(client)} ({client_ref})</div>
          <div class="meta">Risk profile: {risk_profile['Name'] if risk_profile else '—'}
              &nbsp;|&nbsp; Portfolio value: {value_str}
              &nbsp;|&nbsp; {portfolio.get('Name') or 'Portfolio'}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    bundles = build_client_priorities(view, ref)
    bundle = bundles[0]

    st.subheader("Active priorities")
    if bundle["priorities"]:
        for item in bundle["priorities"]:
            _render_priority(item)
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
                st.warning(
                    "Market news search failed (network/provider error) — "
                    "briefing will note this rather than claim no news exists."
                )

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

        _render_sources(briefing.get("sources") or [])


def _render_sources(sources: list[dict]) -> None:
    """
    Renders synthesis.context_builder's code-built audit trail — never
    text the model wrote. A news_article entry with a real link gets a
    clickable reference; everything else (priority facts, risk
    contributors, house view, CRM notes/tags) is traceable by its label
    and fact_id instead, since none of those have a natural URL.
    """
    st.markdown("### 🔗 Sources")
    if not sources:
        st.caption("No sourced facts were used to produce this briefing.")
        return

    labels = {
        "priority_fact": "Portfolio priorities",
        "risk_contributor": "Risk contributors",
        "house_view": "Bank house view",
        "news_article": "Market news",
        "client_note": "CRM notes",
        "client_interest_tag": "CRM interest tags",
    }
    for source_type, heading in labels.items():
        group = [s for s in sources if s["type"] == source_type]
        if not group:
            continue
        with st.expander(f"{heading} ({len(group)})"):
            for source in group:
                if source.get("url"):
                    st.markdown(f"- [{source['label']}]({source['url']})")
                else:
                    st.markdown(f"- {source['label']}")


def main() -> None:
    clients, ref = _load_clients_and_ref()
    selected_client_ref = st.session_state.get("selected_client_ref")

    if selected_client_ref:
        render_client_detail(clients, ref, selected_client_ref)
    else:
        render_client_list(clients, ref)


main()
