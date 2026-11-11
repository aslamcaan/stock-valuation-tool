"""Finnhub: fallback for quote, market cap, beta, beat/miss history, ratings, news, insiders.

Free plan: 60 calls/minute. Foreign companies may map to their home listing (ASML -> ASML.AS);
the profile's `currency` then refers to that listing, so callers must check it.
"""
from __future__ import annotations

from core.cache import Cache, Cached
from core.http import DataSourceError, RateLimiter, cache_key, get

SOURCE = "Finnhub"
BASE = "https://finnhub.io/api/v1/"
_LIMITER = RateLimiter(per_second=1)

# endpoint name -> (path, cache category)
ENDPOINTS = {
    "quote": ("quote", "price"),
    "profile": ("stock/profile2", "reference"),
    "metric": ("stock/metric", "reference"),
    "earnings": ("stock/earnings", "estimates"),
    "earnings_calendar": ("calendar/earnings", "estimates"),
    "recommendation": ("stock/recommendation", "estimates"),
    "company_news": ("company-news", "news"),
    "insider_transactions": ("stock/insider-transactions", "fundamentals"),
    "peers": ("stock/peers", "reference"),
}


class FinnhubClient:
    def __init__(self, cache: Cache, api_key: str):
        self.cache = cache
        self._key = api_key

    def call(self, name: str, symbol: str, force: bool = False, **extra) -> Cached:
        path, category = ENDPOINTS[name]
        url = BASE + path
        params = {"symbol": symbol.upper(), **{k: str(v) for k, v in extra.items()}}
        if name == "metric":
            params["metric"] = "all"

        def fetch():
            if not self._key:
                raise DataSourceError(SOURCE, "FINNHUB_API_KEY is not set in .env")
            data = get(SOURCE, url, params=params, limiter=_LIMITER, headers={"X-Finnhub-Token": self._key}).json()
            if isinstance(data, dict) and "error" in data:
                raise DataSourceError(SOURCE, f"{name}: {data['error']}", 403)
            return data

        return self.cache.get_or_fetch(category, cache_key(url, params), fetch, force=force)
