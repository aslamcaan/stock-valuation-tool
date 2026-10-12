"""Streamlit entry point: `streamlit run app.py`."""
from __future__ import annotations

import streamlit as st

st.set_page_config(page_title="Stock Valuation Tool", page_icon="📈", layout="wide")

pages = [
    st.Page("pages/home.py", title="Search", icon=":material/search:", default=True),
    st.Page("pages/track_record.py", title="Track Record", icon=":material/insights:"),
    st.Page("pages/debug.py", title="Debug: raw data", icon=":material/bug_report:"),
]
st.navigation(pages).run()
