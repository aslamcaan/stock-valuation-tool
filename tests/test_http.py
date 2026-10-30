import time

import pytest

from core.http import DataSourceError, RateLimiter, cache_key, get, redact
from tests.conftest import FakeResponse


def test_redact_hides_keys():
    s = "https://x/y?symbol=AAPL&apikey=SECRET123&api_key=S2"
    out = redact(s)
    assert "SECRET123" not in out and "S2" not in out and "symbol=AAPL" in out


def test_cache_key_strips_secrets():
    k = cache_key("https://x/y", {"symbol": "AAPL", "apikey": "SECRET", "api_key": "S"})
    assert "SECRET" not in k and k == "https://x/y?symbol=AAPL"


def test_cache_key_order_independent():
    assert cache_key("u", {"a": 1, "b": 2}) == cache_key("u", {"b": 2, "a": 1})


def test_http_error_message_redacted(fake_get):
    _, responses = fake_get
    responses.append(FakeResponse(status=403, text="denied", url="https://fmp/x?apikey=SECRET"))
    with pytest.raises(DataSourceError) as e:
        get("FMP", "https://fmp/x", params={"apikey": "SECRET"})
    assert "SECRET" not in str(e.value) and e.value.status == 403


def test_rate_limiter_spacing():
    rl = RateLimiter(per_second=20)
    t0 = time.monotonic()
    for _ in range(5):
        rl.wait()
    assert time.monotonic() - t0 >= 4 / 20 - 0.01


def test_a_source_that_keeps_returning_429_fails_fast_afterwards(monkeypatch):
    import time as _t
    import core.http as h
    calls = []

    class R:
        status_code, url, text = 429, "https://x/y", ""

    class S:
        def get(self, *a, **k):
            calls.append(1)
            return R()
    monkeypatch.setattr(h.time, "sleep", lambda s: None)
    h._cooldown.pop("TEST", None)
    for _ in range(2):
        try:
            h.get("TEST", "https://x/y", session=S())
        except h.DataSourceError as e:
            assert e.status == 429
    assert len(calls) == 3  # the second request did not reach the network
    h._cooldown.pop("TEST", None)


def test_a_quota_message_is_not_retried_and_cools_down_longer(monkeypatch):
    import core.http as h
    calls = []

    class R:
        status_code, url, text = 429, "https://x/y", '{"Error Message": "Limit Reach . Please upgrade your plan"}'

    class S:
        def get(self, *a, **k):
            calls.append(1)
            return R()
    monkeypatch.setattr(h.time, "sleep", lambda s: None)
    h._cooldown.pop("TESTQ", None)
    try:
        h.get("TESTQ", "https://x/y", session=S())
    except h.DataSourceError:
        pass
    assert len(calls) == 1
    assert h._cooldown["TESTQ"] - h.time.monotonic() > h.SHORT_COOLDOWN_SECONDS
    h._cooldown.pop("TESTQ", None)
