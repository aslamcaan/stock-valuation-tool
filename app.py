"""Streamlit entry point: `streamlit run app.py`.

Pages live in views/, not pages/: Streamlit auto-builds a sidebar menu from a pages/ folder, and that menu would let
a visitor open a page without passing the password gate. Every page runs through this file, so the gate runs first.
"""
from __future__ import annotations

import streamlit as st

from ui.auth import logout_button, require_password
from ui.format import CSS

st.set_page_config(page_title="Stock Valuation Tool", page_icon="📈", layout="wide")
st.markdown(CSS, unsafe_allow_html=True)

pages = [
    st.Page("views/home.py", title="Search", icon=":material/search:", default=True),
    st.Page("views/report.py", title="Report", icon=":material/description:"),
    st.Page("views/compare.py", title="Compare", icon=":material/compare_arrows:"),
    st.Page("views/track_record.py", title="Track Record", icon=":material/insights:"),
    st.Page("views/debug.py", title="Debug: raw data", icon=":material/bug_report:"),
]
authed = require_password(stop=False)
nav = st.navigation(pages, position="sidebar" if authed else "hidden")
if not authed:
    st.stop()  # no page code runs, whatever URL was requested
logout_button()
nav.run()
