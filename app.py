"""Streamlit entry point: `streamlit run app.py`."""
from __future__ import annotations

import streamlit as st

from ui.auth import logout_button, require_password
from ui.format import CSS

st.set_page_config(page_title="Stock Valuation Tool", page_icon="📈", layout="wide")
st.markdown(CSS, unsafe_allow_html=True)
require_password()

pages = [
    st.Page("pages/home.py", title="Search", icon=":material/search:", default=True),
    st.Page("pages/report.py", title="Report", icon=":material/description:"),
    st.Page("pages/track_record.py", title="Track Record", icon=":material/insights:"),
    st.Page("pages/debug.py", title="Debug: raw data", icon=":material/bug_report:"),
]
nav = st.navigation(pages)
logout_button()
nav.run()
