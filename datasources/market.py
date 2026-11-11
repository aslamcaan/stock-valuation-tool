"""Market data with provider fallback: FMP first, then free sources when FMP refuses a symbol.

Every result records which provider answered and, if a fallback was used, why. With a paid FMP
plan the fallbacks simply stop being used; no code change is needed.

All outputs are normalised to provider-independent shapes (documented per method).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable

from core.cache import Cached, CacheMiss
from core.http import DataSourceError
from datasources.finnhub import FinnhubClient
from datasources.fmp import FmpClient
from datasources.tiingo import TiingoClient


@dataclass
class MarketResult:
    data: Any  # normalised payload, or None when no provider could answer
    source: str | None
    fetched_at: str | None
    from_cache: bool = False
    notes: list[str] = field(default_factory=list)  # why earlier providers were skipped

    @property
    def available(self) -> bool:
        return self.data is not None

    @property
    def used_fallback(self) -> bool:
        return bool(self.notes) and self.available


Attempt = tuple[str, Callable[[], Cached], Callable[[Any], Any]]


def _first(attempts: list[Attempt], missing_note: str | None = None) -> MarketResult:
    notes: list[str] = []
    for source, call, normalise in attempts:
        try:
            c = call()
            data = None if c.payload in (None, [], {}) else normalise(c.payload)
        except (DataSourceError, CacheMiss) as exc:
            notes.append(f"{source}: {_reason(exc)}")
            continue
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            notes.append(f"{source}: unexpected response ({type(exc).__name__})")
            continue
        if data in (None, [], {}):
            notes.append(f"{source}: no data returned")
            continue
        return MarketResult(data, source, c.fetched_at_iso, c.from_cache, notes)
    if missing_note:
        notes.append(missing_note)
    return MarketResult(None, None, None, False, notes)


def _reason(exc: Exception) -> str:
    if isinstance(exc, CacheMiss):
        return "not in offline cache"
    status = getattr(exc, "status", None)
    if status in (401, 402, 403):
        return "not available on the current plan for this symbol"
    return str(exc)[:160]


STALE_HOURS = 6  # a quote older than this is not "latest" while the market is open; others are asked


def _when(iso: str | None) -> datetime | None:
    try:
        d = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _is_stale(iso: str | None) -> bool:
    d = _when(iso)
    return d is None or datetime.now(timezone.utc) - d > timedelta(hours=STALE_HOURS)


def _ts(epoch: int | float | None) -> str | None:
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat(timespec="seconds") if epoch else None


class MarketData:
    def __init__(self, fmp: FmpClient, tiingo: TiingoClient, finnhub: FinnhubClient):
        self.fmp, self.tiingo, self.finnhub = fmp, tiingo, finnhub

    # --- prices --------------------------------------------------------------------------
    def quote(self, symbol: str) -> MarketResult:
        """{price, as_of} in the US listing's currency (US$): the latest price any provider has, intraday included.
        The first provider answers unless its price is more than a few hours old; then the others are asked and the
        newest timestamp wins, so a stale close is not used when a fresher price exists."""
        attempts = [
            ("FMP", lambda: self.fmp.call("quote", symbol),
             lambda p: {"price": float(p[0]["price"]), "as_of": _ts(p[0].get("timestamp"))}),
            ("Tiingo", lambda: self.tiingo.quote(symbol),
             lambda p: {"price": float(p[0].get("tngoLast") or p[0].get("last") or p[0]["prevClose"]),
                        "as_of": p[0].get("timestamp")}),
            ("Finnhub", lambda: self.finnhub.call("quote", symbol),
             lambda p: {"price": float(p["c"]), "as_of": _ts(p.get("t"))} if p.get("c") else None),
        ]
        first = _first(attempts)
        if not first.available or not _is_stale(first.data.get("as_of")):
            return first
        best, notes = first, list(first.notes) + [f"{first.source}: price as of {first.data.get('as_of') or 'unknown'} "
                                                  "looked stale: other providers asked"]
        for i, att in enumerate(attempts):
            if att[0] == first.source:
                continue
            alt = _first([att])
            if alt.available and (_when(alt.data.get("as_of")) or datetime.min.replace(tzinfo=timezone.utc)) >                     (_when(best.data.get("as_of")) or datetime.min.replace(tzinfo=timezone.utc)):
                best = alt
        best.notes = notes + ([f"{best.source} had the newest price"] if best.source != first.source else [])
        return best

    def next_earnings(self, symbol: str, today: date | None = None) -> MarketResult:
        """{date, eps_estimate} of the next results announcement on or after today, from an earnings calendar."""
        t = (today or date.today()).isoformat()

        def fmp_norm(p):
            rows = sorted((r for r in p if r.get("date", "")[:10] >= t and r.get("epsActual") is None),
                          key=lambda r: r["date"])
            return {"date": rows[0]["date"][:10], "eps_estimate": rows[0].get("epsEstimated")} if rows else None

        def fh_norm(p):
            rows = sorted((r for r in (p or {}).get("earningsCalendar", []) if r.get("date", "")[:10] >= t),
                          key=lambda r: r["date"])
            return {"date": rows[0]["date"][:10], "eps_estimate": rows[0].get("epsEstimate")} if rows else None

        end = ((today or date.today()) + timedelta(days=120)).isoformat()
        return _first([
            ("FMP", lambda: self.fmp.call("earnings", symbol), fmp_norm),
            ("Finnhub", lambda: self.finnhub.call("earnings_calendar", symbol, **{"from": t, "to": end}), fh_norm),
        ], missing_note="No earnings calendar available: the next results date is not known.")

    def price_history(self, symbol: str, start: str) -> MarketResult:
        """[{date, close, adj_close}] ascending by date. FMP light has no adjusted close (adj_close=None)."""
        def fmp_norm(p):
            rows = [{"date": r["date"][:10], "close": float(r["price"]), "adj_close": None}
                    for r in p if r["date"][:10] >= start]
            return sorted(rows, key=lambda r: r["date"])

        def tiingo_norm(p):
            return [{"date": r["date"][:10], "close": float(r["close"]), "adj_close": float(r["adjClose"])}
                    for r in p]

        return _first([
            ("FMP", lambda: self.fmp.call("price_history", symbol, **{"from": start}), fmp_norm),
            ("Tiingo", lambda: self.tiingo.prices(symbol, start), tiingo_norm),
        ])

    def market_cap(self, symbol: str) -> MarketResult:
        """{market_cap (units of currency), currency, as_of, listing}. Finnhub may quote the home listing."""
        return _first([
            ("FMP", lambda: self.fmp.call("market_cap", symbol),
             lambda p: {"market_cap": float(p[0]["marketCap"]), "currency": "USD", "as_of": p[0].get("date"),
                        "listing": symbol.upper()}),
            ("Finnhub", lambda: self.finnhub.call("profile", symbol),
             lambda p: {"market_cap": float(p["marketCapitalization"]) * 1e6, "currency": p.get("currency"),
                        "as_of": None, "listing": p.get("ticker")} if p.get("marketCapitalization") else None),
        ])

    def beta(self, symbol: str) -> MarketResult:
        """{beta}: provider regression beta."""
        return _first([
            ("FMP", lambda: self.fmp.call("profile", symbol),
             lambda p: {"beta": float(p[0]["beta"])} if p and p[0].get("beta") is not None else None),
            ("Finnhub", lambda: self.finnhub.call("metric", symbol),
             lambda p: {"beta": float(p["metric"]["beta"])} if p["metric"].get("beta") is not None else None),
        ])

    def profile(self, symbol: str) -> MarketResult:
        """FMP profile dict (works for all symbols on the free plan)."""
        return _first([("FMP", lambda: self.fmp.call("profile", symbol), lambda p: p[0] if p else None)])

    def peers(self, symbol: str) -> MarketResult:
        """[ticker, ...] excluding the company itself."""
        return _first([
            ("FMP", lambda: self.fmp.call("peers", symbol),
             lambda p: [r["symbol"] for r in p if r["symbol"].upper() != symbol.upper()]),
            ("Finnhub", lambda: self.finnhub.call("peers", symbol),
             lambda p: [s for s in p if s.upper() != symbol.upper() and "." not in s]),
        ])

    # --- analysts --------------------------------------------------------------------------
    def analyst_estimates(self, symbol: str) -> MarketResult:
        """FMP rows as returned (annual consensus). No free alternative exists."""
        return _first([("FMP", lambda: self.fmp.call("analyst_estimates", symbol), lambda p: p)],
                      missing_note="No free source for analyst estimates; forecast falls back to history.")

    def price_target(self, symbol: str) -> MarketResult:
        """{median, high, low, consensus, analysts} where available."""
        def norm(p):
            c = p[0]
            return {"median": c.get("targetMedian"), "high": c.get("targetHigh"), "low": c.get("targetLow"),
                    "consensus": c.get("targetConsensus")}
        return _first([("FMP", lambda: self.fmp.call("price_target_consensus", symbol), norm)],
                      missing_note="No free source for analyst price targets.")

    def ratings(self, symbol: str) -> MarketResult:
        """{strong_buy, buy, hold, sell, strong_sell, as_of}."""
        return _first([
            ("FMP", lambda: self.fmp.call("grades_consensus", symbol),
             lambda p: {"strong_buy": p[0]["strongBuy"], "buy": p[0]["buy"], "hold": p[0]["hold"],
                        "sell": p[0]["sell"], "strong_sell": p[0]["strongSell"], "as_of": None}),
            ("Finnhub", lambda: self.finnhub.call("recommendation", symbol),
             lambda p: {"strong_buy": p[0]["strongBuy"], "buy": p[0]["buy"], "hold": p[0]["hold"],
                        "sell": p[0]["sell"], "strong_sell": p[0]["strongSell"], "as_of": p[0]["period"]}),
        ])

    def earnings_history(self, symbol: str) -> MarketResult:
        """[{date, eps_actual, eps_estimate, revenue_actual, revenue_estimate}] newest first.
        Finnhub's free tier covers only the last 4 quarters and no revenue."""
        return _first([
            ("FMP", lambda: self.fmp.call("earnings", symbol),
             lambda p: [{"date": r["date"], "eps_actual": r.get("epsActual"), "eps_estimate": r.get("epsEstimated"),
                         "revenue_actual": r.get("revenueActual"), "revenue_estimate": r.get("revenueEstimated")}
                        for r in p if r.get("epsActual") is not None]),
            ("Finnhub", lambda: self.finnhub.call("earnings", symbol),
             lambda p: [{"date": r["period"], "eps_actual": r.get("actual"), "eps_estimate": r.get("estimate"),
                         "revenue_actual": None, "revenue_estimate": None} for r in p]),
        ])

    # --- news and insiders (Release 2) ----------------------------------------------------
    def company_news(self, symbol: str, start: str, end: str) -> MarketResult:
        """[{headline, source, url, published, summary}]."""
        return _first([
            ("FMP", lambda: self.fmp.call("news", symbol, **{"from": start, "to": end}),
             lambda p: [{"headline": r["title"], "source": r.get("site") or r.get("publisher"), "url": r["url"],
                         "published": r["publishedDate"], "summary": r.get("text", "")} for r in p]),
            ("Finnhub", lambda: self.finnhub.call("company_news", symbol, **{"from": start, "to": end}),
             lambda p: [{"headline": r["headline"], "source": r.get("source"), "url": r["url"],
                         "published": _ts(r.get("datetime")), "summary": r.get("summary", "")} for r in p]),
        ])

    def insider_transactions(self, symbol: str) -> MarketResult:
        """Provider rows; SEC Form 4 parsing replaces this in Release 2."""
        return _first([
            ("FMP", lambda: self.fmp.call("insider_trading", symbol), lambda p: p),
            ("Finnhub", lambda: self.finnhub.call("insider_transactions", symbol), lambda p: p.get("data")),
        ])

    # --- diagnostics --------------------------------------------------------------------------
    def coverage(self, symbol: str) -> list[dict]:
        """Which provider answers each data item for `symbol` (used at checkpoints and on the Debug page)."""
        checks = {
            "quote": lambda: self.quote(symbol),
            "price_history": lambda: self.price_history(symbol, f"{date.today().year - 5}-01-01"),
            "market_cap": lambda: self.market_cap(symbol),
            "beta": lambda: self.beta(symbol),
            "peers": lambda: self.peers(symbol),
            "analyst_estimates": lambda: self.analyst_estimates(symbol),
            "price_target": lambda: self.price_target(symbol),
            "ratings": lambda: self.ratings(symbol),
            "earnings_history": lambda: self.earnings_history(symbol),
            "company_news": lambda: self.company_news(symbol, (date.today() - timedelta(days=14)).isoformat(),
                                                       date.today().isoformat()),
            "insider_transactions": lambda: self.insider_transactions(symbol),
        }
        rows = []
        for item, fn in checks.items():
            r = fn()
            rows.append({"item": item, "source": r.source or "unavailable",
                         "rows": len(r.data) if isinstance(r.data, list) else (1 if r.available else 0),
                         "notes": "; ".join(r.notes)})
        return rows
