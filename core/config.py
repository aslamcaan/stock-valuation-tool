"""Settings loaded from .env (local) or Streamlit secrets (deployed).

Secrets are held here and nowhere else. Never log or print a Settings object's key fields;
use `Settings.redacted()` for diagnostics.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field, fields
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SECRET_FIELDS = {"fmp_api_key", "fred_api_key", "anthropic_api_key", "app_password", "database_url"}


def _streamlit_secret(name: str) -> str | None:
    try:
        import streamlit as st

        if name in st.secrets:
            return str(st.secrets[name])
    except Exception:  # no secrets file, or not running under Streamlit
        pass
    return None


def _get(name: str, default: str = "") -> str:
    value = os.environ.get(name)
    if value is None or value == "":
        value = _streamlit_secret(name)
    return (value if value is not None else default).strip().strip('"').strip("'")


def _float(name: str, default: float) -> float:
    raw = _get(name)
    try:
        return float(raw) if raw else default
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    sec_user_name: str = ""
    sec_user_email: str = ""
    fmp_api_key: str = field(default="", repr=False)
    fred_api_key: str = field(default="", repr=False)
    anthropic_api_key: str = field(default="", repr=False)
    max_cost_per_report: float = 0.50
    max_cost_per_day: float = 2.00
    app_password: str = field(default="", repr=False)
    database_url: str = field(default="", repr=False)
    cache_dir: Path = PROJECT_ROOT / ".cache"
    offline: bool = False  # serve only from cache, never hit the network

    @property
    def sec_user_agent(self) -> str:
        return f"{self.sec_user_name} {self.sec_user_email}".strip()

    def redacted(self) -> dict:
        out = {}
        for f in fields(self):
            v = getattr(self, f.name)
            out[f.name] = ("set" if v else "missing") if f.name in SECRET_FIELDS else v
        return out


def load_settings() -> Settings:
    load_dotenv(PROJECT_ROOT / ".env", override=False)
    cache_dir = _get("VT_CACHE_DIR")
    return Settings(
        sec_user_name=_get("SEC_USER_NAME"),
        sec_user_email=_get("SEC_USER_EMAIL"),
        fmp_api_key=_get("FMP_API_KEY"),
        fred_api_key=_get("FRED_API_KEY"),
        anthropic_api_key=_get("ANTHROPIC_API_KEY"),
        max_cost_per_report=_float("MAX_COST_PER_REPORT", 0.50),
        max_cost_per_day=_float("MAX_COST_PER_DAY", 2.00),
        app_password=_get("APP_PASSWORD"),
        database_url=_get("DATABASE_URL"),
        cache_dir=Path(cache_dir) if cache_dir else PROJECT_ROOT / ".cache",
        offline=_get("VT_OFFLINE").lower() in {"1", "true", "yes"},
    )
