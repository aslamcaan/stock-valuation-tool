"""Data desk: fiscal-year-end points for historical multiples and the 52-week range."""
from __future__ import annotations

from datetime import date, timedelta

from core.cache import CacheMiss
from core.http import DataSourceError
from engine.history_multiples import YearPoint, price_on_or_before, split_adjusted_closes
from engine.model import Historicals


def price_series(svc, ticker: str, start: date) -> tuple[dict[str, float], str]:
    """Split-adjusted (not dividend-adjusted) closes. Tiingo carries split factors; FMP is the fallback."""
    try:
        c = svc.tiingo.prices(ticker, start.isoformat())
        if c.payload:
            return split_adjusted_closes(c.payload), f"Tiingo daily closes, split-adjusted (fetched {c.fetched_at_iso})"
    except (DataSourceError, CacheMiss):
        pass
    r = svc.market.price_history(ticker, start.isoformat())
    if r.available:
        return {x["date"]: x["close"] for x in r.data}, f"{r.source} daily closes (split adjustment as provided)"
    return {}, "price history unavailable"


def year_points(h: Historicals, closes: dict[str, float], adr_ratio: float = 1.0) -> list[YearPoint]:
    """Prices are per US share; XBRL share counts are ordinary shares, so prices are divided by the ADR ratio."""
    pts = []
    for p in h.periods:
        if p.kind != "FY":
            continue
        px = price_on_or_before(closes, p.end)
        shares = h.v("shares_diluted_weighted", p.label) or h.v("shares_basic_weighted", p.label)
        debt = h.v("debt_for_valuation", p.label)
        pts.append(YearPoint(p.label, p.end, px / adr_ratio if px else None, shares,
                             debt if debt is not None else h.v("total_debt", p.label),
                             h.v("cash_and_investments", p.label), h.v("minority_interest", p.label) or 0.0,
                             h.v("revenue", p.label), h.v("ebitda", p.label), h.v("fcf", p.label),
                             h.v("net_income_attributable", p.label)))
    return pts


def week52(closes: dict[str, float], today: date) -> tuple[float, float] | None:
    lo = (today - timedelta(days=365)).isoformat()
    xs = [v for d, v in closes.items() if d >= lo]
    return (min(xs), max(xs)) if xs else None
