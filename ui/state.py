"""Streamlit-cached singletons shared across pages."""
from __future__ import annotations

import streamlit as st

from core.services import Services, build_services


@st.cache_resource
def get_services() -> Services:
    return build_services()
