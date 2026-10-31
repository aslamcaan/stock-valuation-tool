"""Data desk: fiscal-year-end points for historical multiples and the 52-week range.

Prices are split-adjusted back through every split. XBRL share counts are restated only by filings made after a
split, so each year's count is multiplied by the splits that happened after the filing it came from; otherwise a
pre-split count would be paired with a split-adjusted price (e.g. NVDA FY2022 P/E would read 6 instead of ~59).
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone

from core.cache import CacheMiss
from core.http import DataSourceError
from engine.history_multiples import YearPoint, price_on_or_before, split_adjusted_closes
from engine.model import Historicals

STALE_PRICES_OK = timedelta(days=3)


def price_series(svc, ticker: str, start: date) -> tuple[dict[str, float], str, list[tuple[str, float]]]:
    """(split-adjusted closes, description, [(split date, factor)]). Tiingo carries split factors; FMP fallback."""
    def tiingo(c, how: str):
        splits = [(r["date"][:10], float(r["splitFactor"])) for r in c.payload
                  if r.get("splitFactor") not in (None, 1, 1.0)]
        return split_adjusted_closes(c.payload), f"Tiingo daily closes, split-adjusted ({how} {c.fetched_at_iso})", splits

    try:
        c = svc.tiingo.prices(ticker, start.isoformat())
        if c.payload:
            return tiingo(c, "fetched")
    except (DataSourceError, CacheMiss):
        # e.g. the hourly limit: a series stored in the last few days is still right for multiples and ranges
        c = svc.tiingo.prices_cached(ticker, start.isoformat())
        if c is not None and c.payload and datetime.now(timezone.utc) - c.fetched_at <= STALE_PRICES_OK:
            return tiingo(c, "refresh refused, so the copy fetched")
    r = svc.market.price_history(ticker, start.isoformat())
    if r.available:
        return {x["date"]: x["close"] for x in r.data}, f"{r.source} daily closes (split adjustment as provided)", []
    return {}, "price history unavailable", []


def _filed(v) -> str | None:
    """Filing date of a Value (or of its first input for derived values)."""
    for x in [v] + list(getattr(v, "inputs", ())):
        m = re.search(r"filed (\d{4}-\d{2}-\d{2})", x.filing or "") if x is not None else None
        if m:
            return m.group(1)
    return None


def restated_shares(v, splits: list[tuple[str, float]]) -> float | None:
    if v is None or v.value is None:
        return None
    filed = _filed(v)
    factor = 1.0
    for d, f in splits:
        if filed is None or d > filed:
            factor *= f
    return v.value * factor


def year_points(h: Historicals, closes: dict[str, float], adr_ratio: float = 1.0,
                splits: list[tuple[str, float]] | None = None) -> list[YearPoint]:
    """Prices are per US share; XBRL share counts are ordinary shares, so prices are divided by the ADR ratio."""
    pts = []
    for p in h.periods:
        if p.kind != "FY":
            continue
        px = price_on_or_before(closes, p.end)
        sv = h.get("shares_diluted_weighted", p.label) or h.get("shares_basic_weighted", p.label)
        shares = restated_shares(sv, splits or [])
        debt = h.v("debt_for_valuation", p.label)
        if debt is None:
            debt = h.v("total_debt", p.label)
        if debt is None and h.v("total_assets", p.label) is not None:
            debt = 0.0
        pts.append(YearPoint(p.label, p.end, px / adr_ratio if px else None, shares, debt,
                             h.v("cash_and_investments", p.label), h.v("minority_interest", p.label) or 0.0,
                             h.v("revenue", p.label), h.v("ebitda", p.label), h.v("fcf", p.label),
                             h.v("net_income_attributable", p.label), h.v("operating_income", p.label)))
    return pts


def week52(closes: dict[str, float], today: date) -> tuple[float, float] | None:
    lo = (today - timedelta(days=365)).isoformat()
    xs = [v for d, v in closes.items() if d >= lo]
    return (min(xs), max(xs)) if xs else None
