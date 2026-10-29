"""FX conversion from one dated source (FRED daily rates).

Income statement and cash flow lines use the average rate over the period; balance sheet lines use
the rate at the period end. Every converted number keeps the original value and the rate as inputs.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, timedelta

from data_desk.tags import LINES
from engine.dates import years_earlier
from engine.model import Historicals, Period
from engine.values import RATIO, SHARES_M, Value

INSTANT_DERIVED = {"total_debt", "lease_liabilities", "total_debt_incl_leases", "debt_for_valuation", "cash_and_investments",
                   "net_debt"}


@dataclass(frozen=True)
class FxSeries:
    currency: str
    series_id: str
    usd_per_unit: bool  # True: quote is US$ per 1 unit; False: units per US$
    observations: tuple[tuple[str, float | None], ...]
    fetched_at: str | None = None

    def _usd(self, v: float) -> float:
        return v if self.usd_per_unit else 1.0 / v


class FxRates:
    def __init__(self, series: dict[str, FxSeries]):
        self.series = series

    def _rate_value(self, rate: float, ccy: str, period: str, s: FxSeries, how: str, n: int) -> Value:
        return Value(rate, None, RATIO, period, f"FRED {s.series_id}", tag=s.series_id, fetched_at=s.fetched_at,
                     note=f"US$ per {ccy}, {how} ({n} daily observations)")

    def average(self, ccy: str, start: date, end: date, period: str) -> Value | None:
        s = self.series.get(ccy)
        if s is None:
            return None
        obs = [s._usd(v) for d, v in s.observations if v and start.isoformat() <= d <= end.isoformat()]
        if not obs:
            return None
        return self._rate_value(sum(obs) / len(obs), ccy, period, s, f"average {start} to {end}", len(obs))

    def at(self, ccy: str, when: date, period: str, max_gap_days: int = 7) -> Value | None:
        s = self.series.get(ccy)
        if s is None:
            return None
        lo = (when - timedelta(days=max_gap_days)).isoformat()
        obs = [(d, v) for d, v in s.observations if v and lo <= d <= when.isoformat()]
        if not obs:
            return None
        d, v = obs[-1]
        return self._rate_value(s._usd(v), ccy, period, s, f"period-end rate on {d}", 1)


def _is_instant(line: str) -> bool:
    if line in LINES:
        return LINES[line].kind == "instant"
    return line in INSTANT_DERIVED


def _period_start(p: Period) -> date:
    if p.start:
        return p.start
    return years_earlier(p.end) + timedelta(days=1)


def to_usd(h: Historicals, fx: FxRates) -> tuple[Historicals | None, list[str]]:
    """USD copy of `h`. Returns (None, reasons) if any period lacks a rate."""
    if h.currency == "USD":
        return h, []
    problems: list[str] = []
    rates: dict[tuple[str, str], Value | None] = {}
    for p in h.periods:
        rates[(p.label, "avg")] = fx.average(h.currency, _period_start(p), p.end, p.label)
        rates[(p.label, "end")] = fx.at(h.currency, p.end, p.label)
        for k in ("avg", "end"):
            if rates[(p.label, k)] is None:
                problems.append(f"No FRED {h.currency} rate ({'average' if k == 'avg' else 'period-end'}) for {p.label}")
    if problems:
        return None, problems
    out: dict[str, dict[str, Value]] = {}
    for line, by_period in h.lines.items():
        conv = {}
        for label, v in by_period.items():
            if v.value is None or v.unit in (SHARES_M, RATIO) or v.currency in (None, "USD"):
                conv[label] = v
                continue
            rate = rates.get((label, "end" if _is_instant(line) else "avg"))
            kind = "period-end" if _is_instant(line) else "period-average"
            conv[label] = Value(v.value * rate.value, "USD", v.unit, label, "calculated", tag=v.tag,
                                formula=f"{line} ({h.currency}) x {kind} US$/{h.currency} rate",
                                inputs=(v, rate), input_names=(f"{line} in {h.currency}", f"{kind} rate"))
        out[line] = conv
    return replace(h, currency="USD", lines=out,
                   notes=h.notes + [f"Converted from {h.currency} with FRED rates: period-average for income "
                                    f"statement and cash flow, period-end for balance sheet."]), []


__all__ = ["FxRates", "FxSeries", "to_usd"]
