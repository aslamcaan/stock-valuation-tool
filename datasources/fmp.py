"""Financial Modeling Prep (stable API).

Every endpoint the app uses is listed in ENDPOINTS so `probe()` can report which ones the
user's plan allows. Responses are cached per the TTL of each endpoint's category.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from core.cache import Cache, Cached
from core.http import DataSourceError, RateLimiter, cache_key, get

SOURCE = "FMP"
BASE = "https://financialmodelingprep.com/stable/"
_LIMITER = RateLimiter(per_second=5)


@dataclass(frozen=True)
class Endpoint:
    path: str
    category: str  # cache category -> TTL
    purpose: str
    params: tuple[tuple[str, str], ...] = ()  # fixed extra params
    release: int = 1  # which release first needs it
    symbol_param: str = "symbol"


ENDPOINTS: dict[str, Endpoint] = {
    "profile": Endpoint("profile", "reference", "Company profile, beta, sector, exchange, currency"),
    "quote": Endpoint("quote", "price", "Latest price and market cap"),
    "price_history": Endpoint("historical-price-eod/light", "price", "Daily price history"),
    "shares_float": Endpoint("shares-float", "reference", "Shares outstanding and float"),
    "market_cap": Endpoint("market-capitalization", "price", "Market capitalisation (hard-stop cross-check)"),
    "market_cap_history": Endpoint("historical-market-capitalization", "reference", "Historical market cap"),
    "peers": Endpoint("stock-peers", "reference", "Peer list for comps"),
    "analyst_estimates": Endpoint("analyst-estimates", "estimates", "Consensus revenue/EBIT/EPS estimates",
                                  (("period", "annual"), ("limit", "5"))),
    "price_target_consensus": Endpoint("price-target-consensus", "estimates", "Price target median/high/low"),
    "price_target_summary": Endpoint("price-target-summary", "estimates", "Number of analysts and targets by window"),
    "grades_consensus": Endpoint("grades-consensus", "estimates", "Buy/hold/sell counts"),
    "earnings": Endpoint("earnings", "estimates", "Earnings beat/miss history"),
    "income_statement": Endpoint("income-statement", "fundamentals", "Fallback income statement",
                                 (("period", "annual"), ("limit", "5"))),
    "balance_sheet": Endpoint("balance-sheet-statement", "fundamentals", "Fallback balance sheet",
                              (("period", "annual"), ("limit", "5"))),
    "cash_flow": Endpoint("cash-flow-statement", "fundamentals", "Fallback cash flow",
                          (("period", "annual"), ("limit", "5"))),
    "income_statement_q": Endpoint("income-statement", "fundamentals", "Quarterly income statement (LTM)",
                                   (("period", "quarter"), ("limit", "8"))),
    "key_metrics": Endpoint("key-metrics", "fundamentals", "Historical multiples inputs",
                            (("period", "annual"), ("limit", "5"))),
    "enterprise_values": Endpoint("enterprise-values", "fundamentals", "Historical EV for multiples",
                                  (("period", "annual"), ("limit", "5"))),
    "revenue_segments": Endpoint("revenue-product-segmentation", "fundamentals", "Revenue by segment"),
    "revenue_geography": Endpoint("revenue-geographic-segmentation", "fundamentals", "Revenue by geography (CRP)"),
    "dividends": Endpoint("dividends", "fundamentals", "Dividend history (DDM, capital allocation)"),
    "commodity_quote": Endpoint("quote", "price", "Commodity spot (Brent BZUSD)", symbol_param="symbol"),
    "institutional_ownership": Endpoint("institutional-ownership/symbol-positions-summary", "fundamentals",
                                        "Institutional holders", release=2),
    "insider_trading": Endpoint("insider-trading/search", "fundamentals", "Insider buys/sells", release=2),
    "news": Endpoint("news/stock", "news", "Company news", symbol_param="symbols", release=2),
}

# Probe symbols: a US large cap plus a foreign filer, since some plans restrict non-US symbols.
PROBE_SYMBOLS = {"commodity_quote": "BZUSD"}


class FmpClient:
    def __init__(self, cache: Cache, api_key: str):
        self.cache = cache
        self._key = api_key

    def call(self, name: str, symbol: str, force: bool = False, **extra: Any) -> Cached:
        ep = ENDPOINTS[name]
        params = {ep.symbol_param: symbol.upper(), **dict(ep.params), **{k: str(v) for k, v in extra.items()}}
        url = BASE + ep.path

        def fetch():
            if not self._key:
                raise DataSourceError(SOURCE, "FMP_API_KEY is not set in .env")
            data = get(SOURCE, url, params={**params, "apikey": self._key}, limiter=_LIMITER).json()
            if isinstance(data, dict) and ("Error Message" in data or "error" in data):
                raise DataSourceError(SOURCE, f"{name}: {data.get('Error Message') or data.get('error')}", 402)
            return data

        return self.cache.get_or_fetch(ep.category, cache_key(url, params), fetch, force=force)

    def probe(self, symbols: tuple[str, ...] = ("AAPL", "GRAB")) -> list[dict]:
        """Hit every endpoint once per symbol (bypassing cache) and report availability."""
        rows = []
        for name, ep in ENDPOINTS.items():
            for sym in (PROBE_SYMBOLS.get(name, s) for s in symbols):
                row = {"endpoint": name, "path": ep.path, "symbol": sym, "release": ep.release,
                       "purpose": ep.purpose}
                try:
                    extra = {"year": 2025, "quarter": 2} if name == "institutional_ownership" else {}
                    data = self.call(name, sym, force=True, **extra).payload
                    n = len(data) if isinstance(data, list) else 1
                    row.update(status="ok" if n else "empty", rows=n, detail="")
                except DataSourceError as exc:
                    status = "unavailable" if exc.status in (401, 402, 403) else "error"
                    row.update(status=status, rows=0, detail=str(exc)[:200])
                rows.append(row)
                if name == "commodity_quote":
                    break
        return rows
