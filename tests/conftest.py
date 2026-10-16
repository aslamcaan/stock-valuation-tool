import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
FIXTURES = ROOT / "tests" / "fixtures"

from core.cache import Cache  # noqa: E402


@pytest.fixture
def cache(tmp_path) -> Cache:
    return Cache(tmp_path / "cache")


class FakeResponse:
    def __init__(self, payload=None, status=200, text="", content=b"", url="https://example.test"):
        self._payload, self.status_code, self.text, self.content, self.url = payload, status, text, content, url

    def json(self):
        return self._payload


@pytest.fixture
def fake_get(monkeypatch):
    """Patch requests.get; returns a list of (url, params, headers) calls and a setter for responses."""
    calls, responses = [], []

    def _get(url, params=None, headers=None, timeout=None):
        calls.append({"url": url, "params": params or {}, "headers": headers or {}})
        r = responses.pop(0) if len(responses) > 1 else responses[0]
        return r(url, params) if callable(r) else r

    monkeypatch.setattr("requests.get", _get)
    return calls, responses


def load_edgar_fixture(ticker: str) -> dict:
    import gzip
    import json
    with gzip.open(FIXTURES / "edgar" / f"{ticker}.json.gz", "rt", encoding="utf-8") as fh:
        return json.load(fh)


def historicals_for(ticker: str):
    from data_desk.standardise import standardise
    from data_desk.xbrl import extract
    d = load_edgar_fixture(ticker)
    return standardise(extract(d["companyfacts"], d["fetched_at"]))


@pytest.fixture(autouse=True)
def _isolated_database(tmp_path_factory, monkeypatch):
    """Tests never touch the real data/vt.sqlite or a hosted database."""
    monkeypatch.setenv("VT_DB_PATH", str(tmp_path_factory.mktemp("db") / "vt.sqlite"))
    monkeypatch.setenv("DATABASE_URL", "")
    monkeypatch.setenv("APP_PASSWORD", "")
    monkeypatch.setenv("VT_IGNORE_SECRETS", "1")
