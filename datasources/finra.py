"""FINRA: consolidated short interest (free public API, no key). Published twice a month for each settlement date."""
from __future__ import annotations

from datetime import date, timedelta

import requests

from core.cache import Cache, Cached
from core.http import DataSourceError, cache_key

SOURCE = "FINRA"
URL = "https://api.finra.org/data/group/otcMarket/name/consolidatedShortInterest"


class FinraClient:
    def __init__(self, cache: Cache):
        self.cache = cache

    def short_interest(self, symbol: str, today: date | None = None, days: int = 120) -> Cached:
        """Settlement-date rows for `symbol` over the last `days` (cached a day): settlementDate,
        currentShortPositionQuantity, previousShortPositionQuantity, averageDailyVolumeQuantity,
        daysToCoverQuantity, changePercent."""
        end = today or date.today()
        symbol = symbol.upper().replace("-", "").replace(".", "")  # FINRA writes share classes as BRKB, not BRK-B
        body = {"limit": 50,
                "compareFilters": [{"compareType": "equal", "fieldName": "symbolCode", "fieldValue": symbol.upper()}],
                "dateRangeFilters": [{"fieldName": "settlementDate", "startDate": (end - timedelta(days=days)).isoformat(),
                                      "endDate": end.isoformat()}]}

        def fetch():
            try:
                r = requests.post(URL, json=body, headers={"Accept": "application/json"}, timeout=30)
            except requests.RequestException as exc:
                raise DataSourceError(SOURCE, f"network error: {type(exc).__name__}") from exc
            if r.status_code == 204 or not r.text.strip():
                return []
            if r.status_code >= 400:
                raise DataSourceError(SOURCE, f"HTTP {r.status_code}: {r.text[:200]}", r.status_code)
            try:
                data = r.json()
            except ValueError as exc:
                raise DataSourceError(SOURCE, f"non-JSON response: {r.text[:120]}") from exc
            if not isinstance(data, list) or not all(isinstance(x, dict) for x in data):
                raise DataSourceError(SOURCE, f"unexpected response: {str(data)[:120]}")
            return sorted(data, key=lambda x: x.get("settlementDate", ""))

        return self.cache.get_or_fetch("fundamentals", cache_key(URL, {"symbol": symbol.upper(), "end": end.isoformat(),
                                                                       "days": days}), fetch)
