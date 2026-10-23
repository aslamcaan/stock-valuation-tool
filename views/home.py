"""Landing page: centred company search and recent reports."""
from __future__ import annotations

import streamlit as st
from streamlit_searchbox import st_searchbox

from core.cache import CacheMiss
from core.http import DataSourceError
from datasources.search import label, search
from ui.state import get_services

st.markdown("<h1 style='text-align:center;margin-top:2rem'>Stock Valuation Tool</h1>", unsafe_allow_html=True)
st.markdown("<p style='text-align:center;color:#8b949e'>Equity research and valuation for US-listed companies</p>",
            unsafe_allow_html=True)

_, mid, _ = st.columns([1, 2, 1])
with mid:
    try:
        rows = get_services().edgar.company_tickers().payload
    except (DataSourceError, CacheMiss) as exc:
        st.error(f"Could not load the SEC company list: {exc}")
        st.stop()

    def _search(term: str) -> list[tuple[str, dict]]:
        return [(label(m), m) for m in search(rows, term, limit=10)]

    picked = st_searchbox(_search, label="Stock name or ticker", placeholder="e.g. Grab, UBER, Coca-Cola",
                          key="company_search")
    if picked:
        st.session_state["selected"] = picked
    picked = st.session_state.get("selected")
    if picked:
        st.markdown(f"**{label(picked)}**")
        if st.button("Analyse", type="primary", width="stretch"):
            st.session_state.start_ticker = picked["ticker"]
            st.switch_page("views/report.py")

    st.subheader("Recent reports")
    try:
        reports = get_services().store.recent_reports(12)
    except Exception as exc:  # a database problem should not hide the search
        reports = []
        st.warning(f"Could not load saved reports: {exc}")
    if not reports:
        st.caption("No reports yet. Completed reports appear here and open instantly (no API cost).")
    for r in reports:
        text = f"{r['ticker']} · {r['created_at'][:16].replace('T', ' ')} · {r['headline']}"
        if st.button(text, key=f"open_{r['report_id']}", width="stretch"):
            st.session_state.open_id = r["report_id"]
            st.switch_page("views/report.py")
