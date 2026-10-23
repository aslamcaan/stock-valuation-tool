"""Password gate. The password comes from APP_PASSWORD in the Streamlit secrets (deployed) or .env (local).

If no password is configured, the app only opens when it is running locally (a .env file exists); a deployed app
without APP_PASSWORD stays locked rather than open to anyone with the link.
"""
from __future__ import annotations

import hmac
import time

import streamlit as st

from core.config import PROJECT_ROOT, load_settings

MAX_ATTEMPTS = 5
LOCKOUT_SECONDS = 60


def _login_screen(password: str) -> None:
    st.markdown("<div class='vt-login'><div class='vt-logo'>◆</div><h1>Stock Valuation Tool</h1>"
                "<p class='vt-muted'>Equity research and valuation · private</p></div>",
                unsafe_allow_html=True)
    _, mid, _ = st.columns([1, 1.2, 1])
    with mid:
        locked_until = st.session_state.get("auth_locked_until", 0.0)
        if time.time() < locked_until:
            st.error(f"Too many attempts. Try again in {locked_until - time.time():.0f} seconds.")
            st.stop()
        with st.form("login"):
            entered = st.text_input("Password", type="password", label_visibility="collapsed",
                                    placeholder="Password")
            ok = st.form_submit_button("Enter", type="primary", width="stretch")
        if ok:
            if hmac.compare_digest(entered.encode("utf-8"), password.encode("utf-8")):
                st.session_state.authenticated = True
                st.session_state.pop("auth_failures", None)
                st.rerun()
            failures = st.session_state.get("auth_failures", 0) + 1
            st.session_state.auth_failures = failures
            time.sleep(1)  # slows guessing
            if failures >= MAX_ATTEMPTS:
                st.session_state.auth_locked_until = time.time() + LOCKOUT_SECONDS
                st.session_state.auth_failures = 0
            st.error("Wrong password.")


def require_password(stop: bool = True) -> bool:
    """True once the visitor has entered the password this session. Otherwise shows the login (or locked) screen
    and returns False, or stops the script when `stop` is True."""
    if st.session_state.get("authenticated"):
        return True
    password = load_settings().app_password
    if not password:
        if (PROJECT_ROOT / ".env").exists():
            return True  # local development without a password
        st.error("This app is locked: APP_PASSWORD is not set in the Streamlit secrets.")
    else:
        _login_screen(password)
    if stop:
        st.stop()
    return False


def logout_button() -> None:
    if load_settings().app_password and st.sidebar.button("Log out", width="stretch"):
        st.session_state.clear()
        st.rerun()
