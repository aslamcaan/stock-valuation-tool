"""Tiingo: price and price history fallback when FMP refuses a symbol.

Free plan: roughly 50 requests/hour and 1,000/day, so responses are cached and the key goes in a
header (never the URL).
"""
from __future__ import annotations

from core.cache import Cache, Cached
from core.http import DataSourceError, RateLimiter, cache_key, get

SOURCE = "Tiingo"
BASE = "https://api.tiingo.com/"
_LIMITER = RateLimiter(per_second=2)


class TiingoClient:
    def __init__(self, cache: Cache, api_key: str):
        self.cache = cache
        self._key = api_key

    def _call(self, category: str, path: str, params: dict | None = None, force: bool = False) -> Cached:
        url = BASE + path

        def fetch():
            if not self._key:
                raise DataSourceError(SOURCE, "TIINGO_API_KEY is not set in .env")
            return get(SOURCE, url, params=params, limiter=_LIMITER,
                       headers={"Authorization": f"Token {self._key}", "Content-Type": "application/json"}).json()

        return self.cache.get_or_fetch(category, cache_key(url, params), fetch, force=force)

    def meta(self, symbol: str) -> Cached:
        return self._call("reference", f"tiingo/daily/{symbol.upper()}")

    def quote(self, symbol: str, force: bool = False) -> Cached:
        """IEX real-time-ish quote: list with one dict (tngoLast, prevClose, timestamp)."""
        return self._call("price", f"iex/{symbol.upper()}", force=force)

    def prices(self, symbol: str, start: str, force: bool = False) -> Cached:
        """End-of-day prices from `start` (YYYY-MM-DD): date, close, adjClose, volume..."""
        return self._call("price", f"tiingo/daily/{symbol.upper()}/prices", {"startDate": start}, force=force)
