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
