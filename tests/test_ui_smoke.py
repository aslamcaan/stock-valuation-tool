"""Headless Streamlit smoke tests using a seeded offline cache."""
import pytest
from streamlit.testing.v1 import AppTest

from core.cache import Cache
from core.http import cache_key
from datasources.edgar import TICKERS_URL

TICKERS = [{"cik": 1543151, "name": "Uber Technologies, Inc.", "ticker": "UBER", "exchange": "NYSE"}]


@pytest.fixture
def offline_env(tmp_path, monkeypatch):
    Cache(tmp_path).write("reference", cache_key(TICKERS_URL), TICKERS)
    monkeypatch.setenv("VT_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("VT_OFFLINE", "1")
    from ui.state import get_services
    get_services.clear()
    yield
    get_services.clear()


def test_home_renders(offline_env):
    at = AppTest.from_file("../app.py", default_timeout=30).run()
    assert not at.exception
    assert any("Stock Valuation Tool" in m.value for m in at.markdown)


def test_debug_page_renders_without_keys(offline_env):
    at = AppTest.from_file("../pages/debug.py", default_timeout=30)
    at.session_state["selected"] = TICKERS[0]
    at.run()
    assert not at.exception
