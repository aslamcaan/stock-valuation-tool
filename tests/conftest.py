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
