"""Streamlit-cached singletons shared across pages."""
from __future__ import annotations

import streamlit as st

from core.services import Services, build_services


@st.cache_resource
def get_services() -> Services:
    svc = build_services()
    if not svc.db.is_postgres:
        from desks.pipeline import import_legacy_files

        import_legacy_files(svc.store)  # reports saved as files before the database store
    return svc
