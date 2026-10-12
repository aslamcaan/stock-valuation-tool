"""Provider fallback: FMP first, then Tiingo/Finnhub, with the reason recorded."""
import pytest

from core.cache import Cached
from core.http import DataSourceError
from datasources.market import MarketData


def _c(payload):
    from datetime import datetime, timezone
    return Cached(payload, datetime(2026, 10, 12, tzinfo=timezone.utc), False, "k", "price")


def _refuse(*a, **k):
    raise DataSourceError("FMP", "Premium Query Parameter", 402)


class Stub:
    def __init__(self, **methods):
        self.__dict__.update(methods)


def md(fmp_call=_refuse, tiingo=None, finnhub_call=None):
    return MarketData(Stub(call=fmp_call), tiingo or Stub(), Stub(call=finnhub_call or _refuse))


def test_fmp_used_when_available():
    r = md(fmp_call=lambda name, sym, **k: _c([{"price": 3.2, "timestamp": 1791832431}])).quote("GRAB")
    assert r.source == "FMP" and r.data["price"] == 3.2 and not r.used_fallback


def test_quote_falls_back_to_tiingo_with_reason():
    r = md(tiingo=Stub(quote=lambda s: _c([{"tngoLast": 3.18, "timestamp": "2026-10-12T15:00:00"}]))).quote("GRAB")
    assert r.source == "Tiingo" and r.data["price"] == 3.18
    assert r.used_fallback and "not available on the current plan" in r.notes[0]


def test_quote_falls_back_to_finnhub_when_tiingo_fails():
    def tiingo_down(s):
        raise DataSourceError("Tiingo", "HTTP 500", 500)
    r = md(tiingo=Stub(quote=tiingo_down), finnhub_call=lambda n, s, **k: _c({"c": 3.1, "t": 1791832431})).quote("GRAB")
    assert r.source == "Finnhub" and len(r.notes) == 2


def test_price_history_normalised_ascending():
    rows = [{"date": "2026-10-02T00:00:00.000Z", "close": 2, "adjClose": 2},
            {"date": "2026-10-01T00:00:00.000Z", "close": 1, "adjClose": 1}]
    fmp_rows = [{"date": d["date"][:10], "price": d["close"]} for d in rows]
    r = md(fmp_call=lambda n, s, **k: _c(fmp_rows)).price_history("AAPL", "2026-01-01")
    assert [x["date"] for x in r.data] == ["2026-10-01", "2026-10-02"]
    r = md(tiingo=Stub(prices=lambda s, start: _c(rows[::-1]))).price_history("GRAB", "2026-01-01")
    assert r.source == "Tiingo" and r.data[0]["adj_close"] == 1


def test_market_cap_fallback_keeps_currency():
    profile = {"ticker": "ASML.AS", "currency": "EUR", "marketCapitalization": 600000.0}
    r = md(finnhub_call=lambda n, s, **k: _c(profile)).market_cap("ASML")
    assert r.data == {"market_cap": 600000.0e6, "currency": "EUR", "as_of": None, "listing": "ASML.AS"}


def test_estimates_unavailable_says_so():
    r = md().analyst_estimates("GRAB")
    assert not r.available and "falls back to history" in r.notes[-1]


def test_empty_payload_moves_on():
    r = md(fmp_call=lambda n, s, **k: _c([]),
           finnhub_call=lambda n, s, **k: _c([{"period": "2026-09-01", "strongBuy": 1, "buy": 2, "hold": 3,
                                               "sell": 0, "strongSell": 0}])).ratings("GRAB")
    assert r.source == "Finnhub" and "no data" in r.notes[0]
