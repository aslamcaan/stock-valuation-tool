"""Landing page: centred company search and recent reports."""
from __future__ import annotations

import streamlit as st
from streamlit_searchbox import st_searchbox

from core.cache import CacheMiss
from core.http import DataSourceError
from datasources.search import label, search
from desks.pipeline import load, saved_reports
from ui.state import get_services

st.markdown("<h1 style='text-align:center;margin-top:2rem'>Stock Valuation Tool</h1>", unsafe_allow_html=True)
st.markdown("<p style='text-align:center;color:#5f6b7a'>Equity research and valuation for US-listed companies</p>",
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
            st.switch_page("pages/report.py")

    st.subheader("Recent reports")
    reports = saved_reports()[:12]
    if not reports:
        st.caption("No reports yet. Completed reports appear here and open instantly from disk (no API cost).")
    for path in reports:
        try:
            rep = load(path)
        except Exception:  # an unreadable old file should not break the page
            continue
        vd = rep.model.verdict if rep.model else None
        text = (f"{rep.ticker} · {rep.created_at[:16].replace('T', ' ')} · "
                + (f"{vd.verdict} (fair value ${vd.fair_value:,.2f})" if vd and vd.fair_value else (rep.stopped or "incomplete"))
                + (f" · {rep.md.rating}" if rep.md else ""))
        if st.button(text, key=f"open_{path.stem}", width="stretch"):
            st.session_state.open_path = path
            st.switch_page("pages/report.py")
