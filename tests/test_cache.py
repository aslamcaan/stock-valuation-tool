from datetime import datetime, timedelta, timezone

import pytest

from core.cache import Cache, CacheMiss, TTL_SECONDS


def test_ttls_match_brief():
    assert Cache.ttl("price") == 15 * 60
    assert Cache.ttl("estimates") == 86400
    assert Cache.ttl("fred") == 86400
    assert Cache.ttl("filings") == Cache.ttl("companyfacts") == Cache.ttl("damodaran") == 30 * 86400
    assert Cache.ttl("news") <= 3600
    assert all(Cache.ttl(c) > 0 for c in TTL_SECONDS)


def test_fetch_once_then_cached(cache):
    n = []
    first = cache.get_or_fetch("price", "k", lambda: n.append(1) or {"p": 1})
    second = cache.get_or_fetch("price", "k", lambda: n.append(1) or {"p": 2})
    assert not first.from_cache and second.from_cache
    assert second.payload == {"p": 1} and len(n) == 1
    assert second.fetched_at == first.fetched_at


def test_expired_entry_refetched(cache):
    old = datetime.now(timezone.utc) - timedelta(minutes=16)
    cache.write("price", "k", 1, fetched_at=old)
    assert cache.get_or_fetch("price", "k", lambda: 2).payload == 2


def test_news_never_older_than_one_hour(cache):
    cache.write("news", "k", "old", fetched_at=datetime.now(timezone.utc) - timedelta(minutes=61))
    assert cache.read("news", "k") is None


def test_offline_serves_stale_and_never_fetches(tmp_path):
    online = Cache(tmp_path)
    online.write("price", "k", 7, fetched_at=datetime.now(timezone.utc) - timedelta(days=3))
    offline = Cache(tmp_path, offline=True)
    assert offline.get_or_fetch("price", "k", lambda: pytest.fail("fetched")).payload == 7
    with pytest.raises(CacheMiss):
        offline.get_or_fetch("price", "missing", lambda: 1)


def test_binary_roundtrip(cache):
    cache.get_or_fetch("damodaran", "f", lambda: b"\x00\x01xls", binary=True)
    assert cache.read("damodaran", "f").payload == b"\x00\x01xls"


def test_failed_refresh_falls_back_to_a_recent_copy_but_never_for_prices(tmp_path):
    from datetime import datetime, timedelta, timezone
    from core.cache import Cache
    from core.http import DataSourceError
    c = Cache(tmp_path)
    old = datetime.now(timezone.utc) - timedelta(days=3)
    c.write("reference", "peers-KO", ["PEP"], fetched_at=old)
    c.write("price", "quote-KO", {"price": 90}, fetched_at=old)

    def limited():
        raise DataSourceError("FMP", "rate limited (HTTP 429)", 429)

    def missing():
        raise DataSourceError("FMP", "HTTP 404", 404)

    hit = c.get_or_fetch("reference", "peers-KO", limited)
    assert hit.payload == ["PEP"] and hit.fetched_at == old  # keeps its own date
    assert c.fallbacks and "FMP" in c.fallbacks[-1]
    with pytest.raises(DataSourceError):
        c.get_or_fetch("price", "quote-KO", limited)  # a stale price is never served
    with pytest.raises(DataSourceError):
        c.get_or_fetch("reference", "peers-KO", missing)  # a definite answer is not covered up
    c.write("estimates", "est-KO", [1], fetched_at=datetime.now(timezone.utc) - timedelta(days=10))
    with pytest.raises(DataSourceError):
        c.get_or_fetch("estimates", "est-KO", limited)  # consensus older than a week is not used
