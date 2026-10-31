"""Streamlit entry point: `streamlit run app.py`.

Pages live in views/, not pages/: Streamlit auto-builds a sidebar menu from a pages/ folder, and that menu would let
a visitor open a page without passing the password gate. Every page runs through this file, so the gate runs first.
"""
from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

PACKAGES = ("core", "datasources", "data_desk", "engine", "desks", "exports", "ui", "views")


def _drop_stale_modules() -> None:
    """Streamlit reruns this file on every visit but keeps the project modules it has already imported. After a
    deploy pulls new code into a running server, a new module could import a name an old one lacks (ImportError). So
    when any source file has changed since the last run, the project's modules are dropped and imported afresh."""
    root = Path(__file__).resolve().parent
    stamp = max((f.stat().st_mtime for pkg in PACKAGES for f in (root / pkg).rglob("*.py")), default=0.0)
    last = getattr(sys, "_vt_code_stamp", None)
    sys._vt_code_stamp = stamp
    loaded = [n for n in sys.modules if n.split(".")[0] in PACKAGES]
    # no stamp yet but modules already loaded: they were imported by code from before this check existed
    if loaded and (last is None or stamp > last):
        for name in loaded:
            del sys.modules[name]
        st.cache_resource.clear()  # services built from the old classes


_drop_stale_modules()

from core.config import PROJECT_ROOT, load_settings  # noqa: E402 - after the stale-module check
from ui.auth import log_out, require_password  # noqa: E402
from ui.theme import CSS, install_dollar_guard  # noqa: E402

ASSETS = PROJECT_ROOT / "ui" / "assets"
st.set_page_config(page_title="Stock Valuation Tool", page_icon=":material/bar_chart:", layout="wide",
                   initial_sidebar_state="collapsed")
install_dollar_guard()
st.markdown(CSS, unsafe_allow_html=True)

pages = [
    st.Page("views/home.py", title="Search", icon=":material/search:", default=True),
    st.Page("views/report.py", title="Report", icon=":material/description:"),
    st.Page("views/compare.py", title="Compare", icon=":material/compare_arrows:"),
    st.Page("views/track_record.py", title="Track Record", icon=":material/insights:"),
    st.Page("views/method.py", title="How it works", icon=":material/account_tree:"),
    st.Page("views/interview.py", title="Talking points", icon=":material/record_voice_over:"),
]
if (PROJECT_ROOT / ".env").exists():  # local only: the raw-data page is a developer tool, hidden when deployed
    pages.append(st.Page("views/debug.py", title="Debug", icon=":material/bug_report:"))
if load_settings().app_password:
    pages.append(st.Page(log_out, title="Log out", icon=":material/logout:", url_path="logout"))
authed = require_password(stop=False)
nav = st.navigation(pages, position="top" if authed else "hidden")
if not authed:
    st.stop()  # no page code runs, whatever URL was requested
st.logo(str(ASSETS / "logo.svg"), icon_image=str(ASSETS / "mark.svg"), size="large")
nav.run()
