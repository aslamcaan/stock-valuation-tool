"""Landing page: centred company search and recent reports."""
from __future__ import annotations

import html

import streamlit as st
from streamlit_searchbox import st_searchbox

from core.cache import CacheMiss
from core.http import DataSourceError
from datasources.search import label, search
from ui.format import when
from ui.state import get_services
from ui.theme import LOGO, MUTED, VERDICT_COLOUR, dot

st.markdown(f"<div class='vt-hero'>{LOGO.format(s=46)}<h1>Stock Valuation Tool</h1>"
            "<p>Sell-side style research and valuation for US-listed companies. Every figure traces to a dated "
            "filing or market source.</p></div>", unsafe_allow_html=True)

_, mid, _ = st.columns([1, 2, 1])
with mid:
    try:
        rows = get_services().edgar.company_tickers().payload
    except (DataSourceError, CacheMiss) as exc:
        st.error(f"Could not load the SEC company list: {exc}")
        st.stop()

    def _search(term: str) -> list[tuple[str, dict]]:
        return [(label(m), m) for m in search(rows, term, limit=10)]

    picked = st_searchbox(_search, label="Stock name or ticker", placeholder="Search a company or ticker, e.g. Grab, UBER, Coca-Cola",
                          key="company_search")
    if picked:
        st.session_state["selected"] = picked
    picked = st.session_state.get("selected")
    if picked:
        st.markdown(f"**{label(picked)}**")
        if st.button("Run the report", type="primary", width="stretch",
                     help="Runs all six desks: data, research, modelling, news, review and MD (a few minutes)."):
            st.session_state.start_ticker = picked["ticker"]
            st.switch_page("views/report.py")

st.subheader("Recent reports")
try:
    reports = get_services().store.recent_reports(40)
except Exception as exc:  # a database problem should not hide the search
    reports = []
    st.warning(f"Could not load saved reports: {exc}")
if not reports:
    st.caption("No reports yet. Completed reports appear here and open instantly, at no API cost.")

latest: dict[str, dict] = {}
versions: dict[str, int] = {}
for r in reports:  # newest first: keep each company's latest report, count the earlier versions
    latest.setdefault(r["ticker"], r)
    versions[r["ticker"]] = versions.get(r["ticker"], 0) + 1


def _card(r: dict) -> None:
    head = r["headline"] or ""
    verdict = next((v for v in VERDICT_COLOUR if head.startswith(v)), None)
    rest = head[len(verdict):].strip() if verdict else head
    n = versions[r["ticker"]] - 1
    with st.container(border=True):
        st.markdown(
            f"<div class='vt-rc'><div class='top'><span class='t'>{html.escape(r['ticker'])}</span>"
            f"<span class='d'>{html.escape(when(r['created_at']))}</span></div>"
            f"<div class='h'>{dot(VERDICT_COLOUR.get(verdict, MUTED))}<b>{html.escape(verdict or 'Report')}</b> "
            f"{html.escape(rest)}</div>"
            + (f"<div class='d' style='margin-top:.3rem'>{n} earlier version{'s' if n != 1 else ''}</div>" if n else
               "<div class='d' style='margin-top:.3rem'>&nbsp;</div>")
            + "</div>", unsafe_allow_html=True)
        if st.button("Open", key=f"open_{r['report_id']}", width="stretch",
                     help=f"Report {r['report_id']}: {r['ticker']} {head}"):
            st.session_state.open_id = r["report_id"]
            st.switch_page("views/report.py")


cards = list(latest.values())[:12]
for i in range(0, len(cards), 3):
    cols = st.columns(3)
    for col, r in zip(cols, cards[i:i + 3]):
        with col:
            _card(r)
