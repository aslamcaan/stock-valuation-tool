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
    at = AppTest.from_file("../app.py", default_timeout=30)
    at.session_state["authenticated"] = True
    at.run()
    assert not at.exception
    assert any("Stock Valuation Tool" in m.value for m in at.markdown)
    assert [s.value for s in at.subheader] == ["Recent reports"]


def test_login_required_when_password_set(offline_env, monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "a long test password")
    at = AppTest.from_file("../app.py", default_timeout=30).run()
    assert not at.subheader and len(at.text_input) == 1  # only the login form
    at.switch_page("views/track_record.py").run()
    assert not at.title and len(at.text_input) == 1      # a direct page URL still gets the login form
    at.text_input[0].input("wrong")
    at.button[0].click().run()
    assert [e.value for e in at.error] == ["Wrong password."] and not at.subheader
    at.text_input[0].input("a long test password")
    at.button[0].click().run()
    assert not at.exception and not at.text_input           # logged in: the requested page shows
    assert [t.value for t in at.title] == ["Track Record"]
    at.switch_page("views/home.py").run()
    assert [s.value for s in at.subheader] == ["Recent reports"]


def test_deployed_without_password_stays_locked(offline_env, monkeypatch, tmp_path):
    import ui.auth
    monkeypatch.setattr(ui.auth, "PROJECT_ROOT", tmp_path)  # no .env: looks like a deployment
    at = AppTest.from_file("../app.py", default_timeout=30).run()
    assert not at.subheader and not at.text_input
    assert "APP_PASSWORD is not set" in at.error[0].value
    for page in ("views/home.py", "views/track_record.py", "views/debug.py", "views/report.py"):
        at.switch_page(page).run()  # opening a page's URL directly must not get past the gate
        assert not at.subheader and not at.title and not at.dataframe, page
        assert "APP_PASSWORD is not set" in at.error[0].value


def test_no_pages_folder():
    """A pages/ folder makes Streamlit add its own sidebar menu, which would bypass the password gate."""
    from pathlib import Path
    assert not (Path(__file__).resolve().parent.parent / "pages").exists()


def test_debug_page_runs_data_desk(offline_env):
    at = AppTest.from_file("../views/debug.py", default_timeout=60)
    at.session_state["selected"] = offline_env
    at.run()
    assert not at.exception
    assert at.title and at.title[0].value == "Debug: raw data"
    next(b for b in at.button if b.label == "Run data desk").click().run()
    assert not at.exception
    assert len(at.dataframe) >= 2  # historicals + analysis
    assert any("Net income far above operating income" in m.value for m in at.markdown)
