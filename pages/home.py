"""Landing page: centred company search."""
from __future__ import annotations

import streamlit as st

from core.http import DataSourceError
from datasources.search import label, search
from streamlit_searchbox import st_searchbox
from ui.state import get_services

st.markdown("<h1 style='text-align:center;margin-top:2rem'>Stock Valuation Tool</h1>", unsafe_allow_html=True)
st.markdown("<p style='text-align:center;color:#5f6b7a'>Equity research and valuation for US-listed companies</p>",
            unsafe_allow_html=True)

_, mid, _ = st.columns([1, 2, 1])
with mid:
    try:
        rows = get_services().edgar.company_tickers().payload
    except DataSourceError as exc:
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
        st.success(f"Selected {label(picked)}. Valuation runs arrive in Phase 7; "
                   "use the Debug page to inspect raw data for now.")

    st.subheader("Recent reports")
    st.caption("No reports yet. Completed reports will appear here and open instantly from cache.")
