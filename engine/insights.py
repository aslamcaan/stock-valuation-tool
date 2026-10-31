"""Explaining the valuation (pure): the walk from our DCF to the share price, what the price pays for, a Monte Carlo
range for the DCF and regression-based peer multiples. All are built on run_dcf and the comps data, so they work on
any saved report without new data.

Values are per ordinary share (multiply by the ADR ratio for a US share), like the rest of the DCF output.
"""
from __future__ import annotations

import random
from dataclasses import replace
from statistics import mean

from engine.comps import NM_ABOVE, CompanyMetrics, implied_from_multiple
from engine.dcf import DCFError, DCFInputs, DCFResult, run_dcf, with_changes
from engine.scenarios import DEFAULT_SCENARIOS, STREET_TERMINAL_GROWTH, _solve

ROIC_CAP = 0.40  # today's ROIC is held at most at this level (as in street_conventions)
MIN_STEP = 0.005  # steps that move the value by less than 0.5% are not drawn


# --- 1. walk from our DCF to the share price ----------------------------------------------------------------------
def price_walk(inp: DCFInputs, price: float, effective_tax: float | None, current_roic: float | None,
               current_margin: float | None, risk_free: float) -> list[dict]:
    """One assumption changed at a time, from our DCF towards the share price. When the price is above our value,
    the four common sell-side choices are applied first (each only where it is more generous than ours); the last step
    is the discount rate the price then needs. Each step: {label, detail, value, change}."""
    def value(x: DCFInputs) -> float:
        return run_dcf(x).value_per_share

    cur = inp
    base = value(cur)
    steps = [{"label": "Our DCF", "detail": "the base case", "value": base, "change": 0.0}]

    def add(label: str, detail: str, nxt: DCFInputs) -> None:
        nonlocal cur
        try:
            v = value(nxt)
        except DCFError:
            return
        cur = nxt
        if abs(v - steps[-1]["value"]) >= MIN_STEP * abs(base):  # a change too small to see is applied, not shown
            steps.append({"label": label, "detail": detail, "value": v, "change": v - steps[-1]["value"]})

    if price > base:
        tm = inp.terminal_margin if inp.terminal_margin is not None else inp.years[-1].operating_margin
        if current_margin is not None and current_margin > tm:
            held = tuple(replace(y, operating_margin=max(y.operating_margin, current_margin)) for y in cur.years)
            add("Today's margin held", f"operating margin {current_margin:.1%} kept instead of fading to {tm:.1%}",
                replace(cur, years=held, terminal_margin=current_margin))
        if effective_tax is not None and cur.terminal_tax_rate is not None and 0 <= effective_tax < cur.terminal_tax_rate:
            add("Own tax rate", f"{effective_tax:.1%} (effective) in perpetuity instead of the statutory "
                f"{cur.terminal_tax_rate:.1%}", replace(cur, terminal_tax_rate=effective_tax))
        if current_roic is not None and cur.terminal_roic is not None and min(current_roic, ROIC_CAP) > cur.terminal_roic:
            r = min(current_roic, ROIC_CAP)
            add("Today's ROIC held", f"terminal ROIC {r:.1%} instead of {cur.terminal_roic:.1%} (less reinvestment "
                "needed to grow)", replace(cur, terminal_roic=r))
        g = min(STREET_TERMINAL_GROWTH, risk_free)
        if g > cur.terminal_growth and g < cur.wacc:
            add("3% terminal growth" if g == STREET_TERMINAL_GROWTH else "Higher terminal growth",
                f"{g:.1%} instead of {cur.terminal_growth:.1%}", replace(cur, terminal_growth=g))
    w = _solve(lambda x: value(replace(cur, wacc=x)), price, cur.terminal_growth + 0.005, 0.25)
    if w is not None:
        add("Discount rate the price needs", f"WACC {w:.1%} instead of {cur.wacc:.1%}", replace(cur, wacc=w))
    if abs(steps[-1]["value"] - price) > 0.005 * price:  # the price is out of reach: show what is left unexplained
        steps.append({"label": "Not explained", "detail": "the price is out of reach of these changes",
                      "value": price, "change": price - steps[-1]["value"]})
    return steps


# --- 2. what the price pays for --------------------------------------------------------------------------------------
def value_split(dcf: DCFResult, price: float) -> dict | None:
    """Enterprise value split into today's profits with no growth (year-1 operating profit after tax, held flat for
    ever: NOPAT / WACC) and growth on top; our DCF also split into the forecast years and the terminal value. The
    market's EV (price x shares less the bridge to equity) gets the same no-growth split. None if NOPAT is not
    positive (no meaningful no-growth value)."""
    inp = dcf.inputs
    y1 = inp.years[0]
    nopat = inp.base_revenue * y1.operating_margin * (1 - y1.tax_rate)
    if nopat <= 0 or inp.wacc <= 0:
        return None
    no_growth = nopat / inp.wacc
    bridge = sum(x for _, x in inp.bridge)
    market_ev = price * inp.shares - bridge
    return {"nopat": nopat, "wacc": inp.wacc, "no_growth_ev": no_growth, "ev": dcf.enterprise_value,
            "growth_ev": dcf.enterprise_value - no_growth, "pv_forecast": dcf.sum_pv_fcf,
            "pv_terminal": dcf.pv_terminal_value, "years": len(inp.years), "market_ev": market_ev,
            "market_growth_ev": market_ev - no_growth, "shares": inp.shares, "bridge": bridge}


# --- 3. Monte Carlo range for the DCF --------------------------------------------------------------------------------
Z90 = 1.2816  # the 90th percentile of a standard normal
BEAR, _, BULL = DEFAULT_SCENARIOS
SPREADS = {  # standard deviation of each input: the bear-bull step is its 10th-90th percentile range
    "growth": (BULL.growth_shift - BEAR.growth_shift) / 2 / Z90,
    "margin": (BULL.margin_shift - BEAR.margin_shift) / 2 / Z90,
    "wacc": (BEAR.wacc_shift - BULL.wacc_shift) / 2 / Z90,
    "terminal_growth": (BULL.terminal_growth_shift - BEAR.terminal_growth_shift) / 2 / Z90,
}
PCTS = (5, 10, 25, 50, 75, 90, 95)


def _percentile(xs: list[float], p: float) -> float:
    k = (len(xs) - 1) * p / 100
    lo, hi = int(k), min(int(k) + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)


def monte_carlo(inp: DCFInputs, price: float, n: int = 2000, seed: int = 7,
                max_terminal_growth: float | None = None) -> dict | None:
    """n DCFs, each drawing revenue growth, margin, WACC and terminal growth shifts independently from normal
    distributions whose 10th-90th percentile range equals the bear-to-bull scenario step. The seed is fixed, so the
    result is the same on every run. Terminal growth stays at least 1 point below WACC and under the cap."""
    rng = random.Random(seed)
    values, failed = [], 0
    for _ in range(n):
        gs, ms = rng.gauss(0, SPREADS["growth"]), rng.gauss(0, SPREADS["margin"])
        w = inp.wacc + rng.gauss(0, SPREADS["wacc"])
        g = inp.terminal_growth + rng.gauss(0, SPREADS["terminal_growth"])
        if max_terminal_growth is not None:
            g = min(g, max_terminal_growth)
        g = min(g, w - 0.01)
        try:
            values.append(run_dcf(with_changes(inp, growth_shift=gs, margin_shift=ms, wacc=w, terminal_growth=g))
                          .value_per_share)
        except DCFError:
            failed += 1
    if len(values) < n / 2:
        return None
    values.sort()
    return {"n": n, "valid": len(values), "failed": failed, "values": values, "mean": mean(values),
            "pct": {p: _percentile(values, p) for p in PCTS},
            "prob_above_price": sum(1 for v in values if v > price) / len(values), "spreads": dict(SPREADS),
            "seed": seed}


# --- 4. regression-based peer multiples ------------------------------------------------------------------------------
REGRESSIONS = (  # multiple, the driver that should explain it, labels
    ("ev_sales", "operating_margin", "EV/Sales", "operating margin"),
    ("ev_ebitda", "revenue_growth", "EV/EBITDA", "revenue growth"),
)
MIN_POINTS = 5


def _ols(xs: list[float], ys: list[float]) -> tuple[float, float, float]:
    mx, my = mean(xs), mean(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    b = sxy / sxx
    a = my - b * mx
    ss_tot = sum((y - my) ** 2 for y in ys)
    ss_res = sum((y - a - b * x) ** 2 for x, y in zip(xs, ys))
    return a, b, (1 - ss_res / ss_tot) if ss_tot else 0.0


def peer_regressions(company: CompanyMetrics, peers: list[CompanyMetrics], shares: float, bridge: float,
                     adr_ratio: float = 1.0) -> list[dict]:
    """For each pair, a straight line through the peers (multiple = a + b x driver) and the multiple it gives the
    company at its own driver: a 'warranted' multiple that allows for the company being more or less profitable (or
    growing faster) than the median peer. A cross-check, not part of the fair value."""
    out = []
    for key, driver, label, driver_label in REGRESSIONS:
        pts = [(p.ticker, x, m) for p in peers
               if (x := p.benchmarks.get(driver)) is not None and (m := p.multiples()[key]) is not None
               and 0 < m <= NM_ABOVE[key]]
        mine_x, mine_m = company.benchmarks.get(driver), company.multiples()[key]
        if len(pts) < MIN_POINTS or mine_x is None or len({x for _, x, _ in pts}) < 2:
            out.append({"key": key, "label": label, "driver": driver_label, "points": pts, "applicable": False,
                        "reason": f"needs {MIN_POINTS} peers with both figures ({len(pts)} have them)"})
            continue
        a, b, r2 = _ols([x for _, x, _ in pts], [m for _, _, m in pts])
        warranted = a + b * mine_x
        implied = implied_from_multiple(key, warranted, company, shares, bridge, adr_ratio) if warranted > 0 else None
        xs = [x for _, x, _ in pts]
        out.append({"key": key, "label": label, "driver": driver_label, "points": pts, "applicable": True,
                    "intercept": a, "slope": b, "r2": r2, "company_x": mine_x, "company_multiple": mine_m,
                    "warranted": warranted, "implied_price": implied,
                    "extrapolated": not min(xs) <= mine_x <= max(xs)})
    return out
