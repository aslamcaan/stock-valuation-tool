"""FRED: Treasury yields, FX rates, oil prices."""
from __future__ import annotations

from datetime import date

from core.cache import Cache, Cached
from core.http import DataSourceError, cache_key, get

SOURCE = "FRED"
URL = "https://api.stlouisfed.org/fred/series/observations"

SERIES = {
    "DGS10": "10-year Treasury constant maturity (%)",
    "DCOILBRENTEU": "Brent crude spot (US$/bbl)",
    "DCOILWTICO": "WTI crude spot (US$/bbl)",
}

# Daily FX series. `usd_per_unit` True means the quote is US$ per 1 unit of the currency.
FX_SERIES: dict[str, tuple[str, bool]] = {
    "EUR": ("DEXUSEU", True),
    "GBP": ("DEXUSUK", True),
    "AUD": ("DEXUSAL", True),
    "NZD": ("DEXUSNZ", True),
    "JPY": ("DEXJPUS", False),
    "CNY": ("DEXCHUS", False),
    "CAD": ("DEXCAUS", False),
    "CHF": ("DEXSZUS", False),
    "HKD": ("DEXHKUS", False),
    "INR": ("DEXINUS", False),
    "KRW": ("DEXKOUS", False),
    "SGD": ("DEXSIUS", False),
    "TWD": ("DEXTAUS", False),
    "BRL": ("DEXBZUS", False),
    "MXN": ("DEXMXUS", False),
    "SEK": ("DEXSDUS", False),
    "NOK": ("DEXNOUS", False),
    "DKK": ("DEXDNUS", False),
    "ZAR": ("DEXSFUS", False),
    "THB": ("DEXTHUS", False),
    "MYR": ("DEXMAUS", False),
}


class FredClient:
    def __init__(self, cache: Cache, api_key: str):
        self.cache = cache
        self._key = api_key

    def series(self, series_id: str, start: str = "2008-01-01") -> Cached:
        """Observations as [[date, value or None], ...]; FRED's '.' for missing becomes None."""
        params = {"series_id": series_id, "observation_start": start, "file_type": "json"}

        def fetch():
            if not self._key:
                raise DataSourceError(SOURCE, "FRED_API_KEY is not set in .env")
            raw = get(SOURCE, URL, params={**params, "api_key": self._key}).json()
            return [[o["date"], None if o["value"] == "." else float(o["value"])] for o in raw["observations"]]

        return self.cache.get_or_fetch("fred", cache_key(URL, params), fetch)

    def latest(self, series_id: str) -> tuple[str, float, Cached]:
        c = self.series(series_id, start=f"{date.today().year - 1}-01-01")
        for d, v in reversed(c.payload):
            if v is not None:
                return d, v, c
        raise DataSourceError(SOURCE, f"no observations for {series_id}")
