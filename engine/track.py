"""Track record maths (pure): returns since each call vs benchmarks, hit rates by rating and horizon, and
whether the price moved toward the fair value. Prices come in through a lookup function."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Callable

HORIZONS = {"1m": 30, "3m": 91, "6m": 182, "12m": 365}
BULLISH, BEARISH = ("Strong Buy", "Buy"), ("Sell", "Strong Sell")

PriceAt = Callable[[str, date], float | None]  # (ticker, date) -> close on or before that date


@dataclass
class CallResult:
    call: dict
    price_now: float | None
    ret: float | None
    spy_ret: float | None
    sector_ret: float | None
    toward_fair_value: bool | None
    horizon_excess: dict[str, float | None]


def _ret(price_at: PriceAt, ticker: str, start: date, end: date) -> float | None:
    a, b = price_at(ticker, start), price_at(ticker, end)
    return None if not a or not b else b / a - 1


def evaluate(call: dict, price_at: PriceAt, today: date) -> CallResult:
    d = date.fromisoformat(call["call_date"])
    p0 = call.get("price")
    now = price_at(call["ticker"], today)
    ret = (now / p0 - 1) if now and p0 else None
    spy = _ret(price_at, "SPY", d, today)
    sector = _ret(price_at, call.get("sector_etf") or "SPY", d, today)
    toward = None
    fv = call.get("fair_value")
    if now and p0 and fv:
        toward = abs(now - fv) < abs(p0 - fv)
    excess = {}
    for name, days in HORIZONS.items():
        end = d + timedelta(days=days)
        if end > today:
            excess[name] = None
            continue
        r, m = _ret(price_at, call["ticker"], d, end), _ret(price_at, "SPY", d, end)
        excess[name] = None if r is None or m is None else r - m
    return CallResult(call, now, ret, spy, sector, toward, excess)


def hit_rates(results: list[CallResult]) -> dict[str, dict[str, dict]]:
    """For each rating group and horizon: share of calls that beat (Buys) or lagged (Sells) the S&P 500."""
    out: dict[str, dict[str, dict]] = {}
    for group, ratings, want_positive in (("Buy / Strong Buy", BULLISH, True), ("Sell / Strong Sell", BEARISH, False),
                                          ("Hold", ("Hold",), None)):
        out[group] = {}
        for h in HORIZONS:
            xs = [r.horizon_excess[h] for r in results if r.call.get("rating") in ratings and r.horizon_excess[h] is not None]
            if not xs:
                out[group][h] = {"calls": 0, "hit_rate": None, "average_excess": None}
                continue
            hits = None if want_positive is None else sum(1 for x in xs if (x > 0) == want_positive) / len(xs)
            out[group][h] = {"calls": len(xs), "hit_rate": hits, "average_excess": sum(xs) / len(xs)}
    return out
