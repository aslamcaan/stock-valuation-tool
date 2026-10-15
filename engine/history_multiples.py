"""Historical multiples (pure): where the stock trades now against its own 5-year range.

At each fiscal year end: market cap = split-adjusted share price x diluted shares for that year (XBRL share
counts are restated for splits, so the price must be split-adjusted but not dividend-adjusted). The multiple
uses that year's fundamentals. The implied price applies the 5-year median multiple to current fundamentals.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from statistics import median

from engine.comps import MULTIPLES, earnings_distorted


@dataclass
class YearPoint:
    label: str
    end: date
    price: float | None        # split-adjusted, per ordinary share equivalent of the XBRL share count
    shares: float | None
    debt: float | None
    cash: float | None
    minority: float
    revenue: float | None
    ebitda: float | None
    fcf: float | None
    net_income: float | None
    operating_income: float | None = None

    def multiples(self) -> dict[str, float | None]:
        if self.price is None or not self.shares:
            return {k: None for k in MULTIPLES}
        mcap = self.price * self.shares
        ev = mcap + self.debt - self.cash + self.minority if self.debt is not None and self.cash is not None else None

        def pos(n, d):
            return n / d if n is not None and d and d > 0 and n > 0 else None
        pe = None if earnings_distorted(self.net_income, self.operating_income, self.revenue) \
            else pos(mcap, self.net_income)
        return {"pe_forward": None, "pe_trailing": pe, "ev_sales": pos(ev, self.revenue),
                "ev_ebitda": pos(ev, self.ebitda), "ev_fcf": pos(ev, self.fcf)}


@dataclass
class HistoryResult:
    key: str
    label: str
    series: dict[str, float]          # fiscal year -> multiple
    low: float | None
    median: float | None
    high: float | None
    current: float | None
    percentile: float | None          # where the current multiple sits in the range (0-1)
    implied_price: float | None       # at the 5-year median multiple
    implied_low: float | None
    implied_high: float | None


def split_adjusted_closes(rows: list[dict]) -> dict[str, float]:
    """{date: close / product of split factors after that date} from Tiingo rows (ascending by date)."""
    out: dict[str, float] = {}
    factor = 1.0
    for r in sorted(rows, key=lambda x: x["date"], reverse=True):
        d = r["date"][:10]
        out[d] = float(r["close"]) / factor
        sf = float(r.get("splitFactor") or 1.0)
        if sf and sf != 1.0:
            factor *= sf  # earlier dates are divided by this split as well
    return out


def price_on_or_before(closes: dict[str, float], when: date, max_gap_days: int = 10) -> float | None:
    keys = [d for d in closes if d <= when.isoformat()]
    if not keys:
        return None
    d = max(keys)
    if (when - date.fromisoformat(d)).days > max_gap_days:
        return None
    return closes[d]


def history_multiples(points: list[YearPoint], current: dict[str, float | None], current_metrics: dict,
                      shares: float, bridge: float, adr_ratio: float = 1.0, years: int = 5) -> dict[str, HistoryResult]:
    """`current` = today's multiples; `current_metrics` = {revenue, ebitda, fcf, net_income} used for implied prices."""
    pts = points[-years:]
    out = {}
    metric_for = {"pe_trailing": "net_income", "ev_sales": "revenue", "ev_ebitda": "ebitda", "ev_fcf": "fcf"}
    for key, metric in metric_for.items():
        label = MULTIPLES[key][0]
        series = {p.label: m for p in pts if (m := p.multiples()[key]) is not None}
        cur = current.get(key)
        if len(series) < 3:
            out[key] = HistoryResult(key, label, series, None, None, None, cur, None, None, None, None)
            continue
        vals = sorted(series.values())
        lo, md, hi = vals[0], median(vals), vals[-1]
        pct = None if cur is None else (sum(1 for v in vals if v < cur) + 0.5 * sum(1 for v in vals if v == cur)) / len(vals)
        base = current_metrics.get(metric)

        def implied(mult):
            if base is None or base <= 0 or not shares:
                return None
            if key == "pe_trailing":
                return mult * base / shares * adr_ratio
            return (mult * base + bridge) / shares * adr_ratio
        out[key] = HistoryResult(key, label, series, lo, md, hi, cur, pct, implied(md), implied(lo), implied(hi))
    return out


def implied_price(results: dict[str, HistoryResult]) -> float | None:
    vals = [r.implied_price for r in results.values() if r.implied_price is not None]
    return median(vals) if vals else None
