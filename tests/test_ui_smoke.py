"""Headless Streamlit smoke tests using a seeded offline cache."""
import pytest
from streamlit.testing.v1 import AppTest

from core.cache import Cache
from core.http import cache_key
from datasources.edgar import COMPANYFACTS_URL, SUBMISSIONS_URL, TICKERS_URL
from tests.conftest import load_edgar_fixture


@pytest.fixture
def offline_env(tmp_path, monkeypatch):
    d = load_edgar_fixture("UBER")
    cache = Cache(tmp_path)
    cache.write("reference", cache_key(TICKERS_URL), [d["tickers_row"]])
    cache.write("companyfacts", cache_key(COMPANYFACTS_URL.format(cik=d["cik"])), d["companyfacts"])
    cache.write("filings", cache_key(SUBMISSIONS_URL.format(cik=d["cik"])), d["submissions"])
    monkeypatch.setenv("VT_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("VT_OFFLINE", "1")
    from ui.state import get_services
    get_services.clear()
    yield d["tickers_row"]
    get_services.clear()


def test_home_renders(offline_env):
    at = AppTest.from_file("../app.py", default_timeout=30).run()
    assert not at.exception
    assert any("Stock Valuation Tool" in m.value for m in at.markdown)


def test_debug_page_runs_data_desk(offline_env):
    at = AppTest.from_file("../pages/debug.py", default_timeout=60)
    at.session_state["selected"] = offline_env
    at.run()
    assert not at.exception
    assert at.title and at.title[0].value == "Debug: raw data"
    next(b for b in at.button if b.label == "Run data desk").click().run()
    assert not at.exception
    assert len(at.dataframe) >= 2  # historicals + analysis
    assert any("Net income far above operating income" in m.value for m in at.markdown)
