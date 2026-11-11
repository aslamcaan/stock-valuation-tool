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


# --- price after 1, 3 and 6 months, against the price and the base DCF at the call -----------------------------------
AFTER = {"1m": 30, "3m": 91, "6m": 182}
HOLD_BAND = 0.10  # a Hold is right when the price ends within 10% of where it was at the call


def direction_hit(rating: str | None, change: float | None) -> bool | None:
    """Did the price move the way the rating said? Buys and Strong Buys: up. Sells and Strong Sells: down. Hold: within
    +/-10%. None for an unrated call or a horizon that has not passed."""
    if change is None or not rating or rating == "Not rated":
        return None
    if rating in BULLISH:
        return change > 0
    if rating in BEARISH:
        return change < 0
    if rating == "Hold":
        return abs(change) <= HOLD_BAND
    return None


def horizon_row(call: dict, price_at: PriceAt, today: date, base_dcf: float | None) -> dict:
    """One call: the price at the call, the verdict and base DCF, and the price 1, 3 and 6 months later (None until that
    date has passed or no close was found), each as a move from the call price and a gap to the base DCF."""
    d = date.fromisoformat(call["call_date"])
    p0 = call.get("price")
    row = {"ticker": call["ticker"], "call_date": call["call_date"], "price": p0, "verdict": call.get("verdict"),
           "rating": call.get("rating") or "Not rated", "fair_value": call.get("fair_value"), "base_dcf": base_dcf,
           "report_id": call.get("report_id"), "after": {}}
    for name, days in AFTER.items():
        end = d + timedelta(days=days)
        p = price_at(call["ticker"], end) if end <= today else None
        change = (p / p0 - 1) if p and p0 else None
        row["after"][name] = {"date": end.isoformat(), "elapsed": end <= today, "price": p, "change": change,
                              "vs_base_dcf": (p / base_dcf - 1) if p and base_dcf else None,
                              "hit": direction_hit(row["rating"], change)}
    return row


def hit_rate_by_rating(rows: list[dict]) -> dict[str, dict[str, dict]]:
    """{rating: {horizon: {calls, hits, rate}}} over rows whose horizon has a price. `rate` is None with no calls."""
    out: dict[str, dict[str, dict]] = {}
    for r in rows:
        if r["rating"] == "Not rated":
            continue
        g = out.setdefault(r["rating"], {h: {"calls": 0, "hits": 0, "rate": None} for h in AFTER})
        for h, a in r["after"].items():
            if a["hit"] is None:
                continue
            g[h]["calls"] += 1
            g[h]["hits"] += 1 if a["hit"] else 0
    for g in out.values():
        for v in g.values():
            v["rate"] = v["hits"] / v["calls"] if v["calls"] else None
    return out
