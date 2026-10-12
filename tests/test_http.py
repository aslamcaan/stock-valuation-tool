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
