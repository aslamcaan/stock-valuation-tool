"""Explaining the valuation (pure): the walk from our DCF to the share price, what the price pays for, a Monte Carlo
range for the DCF and regression-based peer multiples. All are built on run_dcf and the comps data, so they work on
any saved report without new data.

Values are per ordinary share (multiply by the ADR ratio for a US share), like the rest of the DCF output.
"""
from __future__ import annotations

import math
import random
from dataclasses import replace
from statistics import mean

from engine.comps import NM_ABOVE, CompanyMetrics, implied_from_multiple
from engine.dcf import DCFError, DCFInputs, DCFResult, _timing, run_dcf, with_changes
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


MIN_CORR_YEARS = 6   # pairs of years needed to measure the growth-margin correlation
MAX_CORR = 0.8       # a correlation from a handful of years is noisy: never treated as near-certain


def growth_margin_correlation(pairs: list[tuple[float, float]]) -> dict | None:
    """Correlation between a company's revenue growth and the change in its operating margin in the same year
    (operating leverage: margins tend to widen in fast-growth years), from its own history. `pairs`: (growth, margin
    change) per year. Clipped to +/-0.8; None with fewer than six years or no variation."""
    if len(pairs) < MIN_CORR_YEARS:
        return None
    xs, ys = [g for g, _ in pairs], [m for _, m in pairs]
    mx, my = mean(xs), mean(ys)
    sxx, syy = sum((x - mx) ** 2 for x in xs), sum((y - my) ** 2 for y in ys)
    if sxx == 0 or syy == 0:
        return None
    r = sum((x - mx) * (y - my) for x, y in pairs) / math.sqrt(sxx * syy)
    return {"raw": r, "rho": max(-MAX_CORR, min(MAX_CORR, r)), "n": len(pairs)}


MIN_POOL_FIRMS, MIN_POOL_YEARS, MIN_FIRM_YEARS = 3, 15, 4


def pooled_growth_margin_correlation(series: dict[str, list[tuple[float, float]]]) -> dict | None:
    """The same correlation pooled across firms (the company and its peers), for a company with too short a history
    of its own. Each firm's growth and margin changes are taken relative to its own averages first, so firms with
    different growth rates do not create a correlation between them (a within-firm estimate). Needs at least three
    firms with four or more years each and fifteen firm-years; clipped to +/-0.8."""
    used = {k: p for k, p in series.items() if len(p) >= MIN_FIRM_YEARS}
    if len(used) < MIN_POOL_FIRMS or sum(len(p) for p in used.values()) < MIN_POOL_YEARS:
        return None
    xs, ys = [], []
    for p in used.values():
        mg, mm = mean(g for g, _ in p), mean(m for _, m in p)
        xs += [g - mg for g, _ in p]
        ys += [m - mm for _, m in p]
    sxx, syy = sum(x * x for x in xs), sum(y * y for y in ys)
    if sxx == 0 or syy == 0:
        return None
    r = sum(x * y for x, y in zip(xs, ys)) / math.sqrt(sxx * syy)
    return {"raw": r, "rho": max(-MAX_CORR, min(MAX_CORR, r)), "n": len(xs), "firms": sorted(used)}


def monte_carlo(inp: DCFInputs, price: float, n: int = 2000, seed: int = 7,
                max_terminal_growth: float | None = None, growth_margin_corr: float = 0.0) -> dict | None:
    """n DCFs, each drawing revenue growth, margin, WACC and terminal growth shifts from normal distributions whose
    10th-90th percentile range equals the bear-to-bull scenario step. Growth and margin shifts are drawn with
    `growth_margin_corr` (0 = independent, the same draws as before); WACC and terminal growth independently. The seed
    is fixed, so the result is the same on every run. Terminal growth stays at least 1 point below WACC and under the
    cap."""
    rng = random.Random(seed)
    rho = growth_margin_corr
    values, failed = [], 0
    for _ in range(n):
        zg, zm = rng.gauss(0, 1), rng.gauss(0, 1)
        gs = SPREADS["growth"] * zg
        ms = SPREADS["margin"] * (rho * zg + math.sqrt(1 - rho * rho) * zm)
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
            "seed": seed, "growth_margin_corr": rho}


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


# --- 5. Dividend cross-check -----------------------------------------------------------------------------------------
MIN_YIELD = 0.01  # below a 1% yield the dividend is too small a part of the return for a dividend model to say much


def dividend_check(dcf: DCFResult, dps0: float, cost_of_equity: float, terminal_growth: float,
                   price: float) -> dict | None:
    """A two-stage dividend discount model in which dividends grow in line with the DCF's forecast operating profit
    after tax (a constant payout), then at terminal growth; discounted at the cost of equity. Also the perpetual
    dividend growth the price implies (Gordon: g = (P x CoE - D0) / (P + D0)). Per ordinary share. None when there
    is no dividend, the yield is below MIN_YIELD, today's NOPAT is not positive or CoE <= terminal growth."""
    if not dps0 or dps0 <= 0 or price <= 0 or dps0 / price < MIN_YIELD or cost_of_equity <= terminal_growth:
        return None
    inp = dcf.inputs
    y1 = inp.years[0]
    nopat0 = inp.base_revenue * y1.operating_margin * (1 - y1.tax_rate)
    if nopat0 <= 0:
        return None
    rows, pv, d = [], 0.0, dps0
    for t, y in enumerate(dcf.years, start=1):
        d = dps0 * max(y.nopat, 0.0) / nopat0
        df = (1 + cost_of_equity) ** -t
        pv += d * df
        rows.append({"year": y.label, "dividend": d, "pv": d * df})
    n = len(rows)
    terminal = d * (1 + terminal_growth) / (cost_of_equity - terminal_growth)
    pv_terminal = terminal * (1 + cost_of_equity) ** -n
    value = pv + pv_terminal
    return {"dps0": dps0, "yield": dps0 / price, "rows": rows, "stage1_cagr": (d / dps0) ** (1 / n) - 1 if d > 0 else None,
            "pv_dividends": pv, "terminal_value": terminal, "pv_terminal": pv_terminal, "value": value,
            "cost_of_equity": cost_of_equity, "terminal_growth": terminal_growth,
            "implied_growth": (price * cost_of_equity - dps0) / (price + dps0), "years": n}


# --- 6. Return on new capital in the forecast ------------------------------------------------------------------------
def return_on_new_capital(dcf: DCFResult) -> dict | None:
    """Damodaran's consistency check: is the forecast reinvesting enough for its growth? The rise in operating profit
    after tax from today (base revenue at the year-1 margin and tax rate) to the final forecast year, divided by the
    reinvestment of every forecast year. None if the forecast reinvests nothing in total."""
    inp = dcf.inputs
    y1 = inp.years[0]
    nopat0 = inp.base_revenue * y1.operating_margin * (1 - y1.tax_rate)
    reinvested = sum(y.reinvestment for y in dcf.years)
    if reinvested <= 0:
        return None
    gain = dcf.years[-1].nopat - nopat0
    return {"nopat0": nopat0, "nopat_final": dcf.years[-1].nopat, "reinvestment": reinvested, "gain": gain,
            "roic_new": gain / reinvested, "years": len(dcf.years), "terminal_roic": inp.terminal_roic,
            "wacc": inp.wacc}


# --- 7. Tornado: which input moves the value most --------------------------------------------------------------------
S2C_STEP = 0.20  # sales-to-capital is not in the bear-bull scenarios: +/-20% (capital needs a fifth lower or higher)


def tornado(inp: DCFInputs, max_terminal_growth: float | None = None) -> list[dict]:
    """The base DCF with one input moved at a time, to its bear and to its bull setting (the scenarios' steps;
    sales-to-capital +/-20%). Rows sorted by the size of the swing: {label, base, low, high, low_detail,
    high_detail}. Values per ordinary share; a move the DCF cannot take (e.g. terminal growth at WACC) is skipped."""
    def value(x: DCFInputs) -> float | None:
        try:
            return run_dcf(x).value_per_share
        except DCFError:
            return None

    base = value(inp)
    if base is None:
        return []
    g_hi = inp.terminal_growth + BULL.terminal_growth_shift
    if max_terminal_growth is not None:
        g_hi = min(g_hi, max(max_terminal_growth, inp.terminal_growth))
    moves = [
        ("Revenue growth", with_changes(inp, growth_shift=BEAR.growth_shift), f"{BEAR.growth_shift * 100:+.0f} pts a year",
         with_changes(inp, growth_shift=BULL.growth_shift), f"{BULL.growth_shift * 100:+.0f} pts a year"),
        ("Operating margin", with_changes(inp, margin_shift=BEAR.margin_shift), f"{BEAR.margin_shift * 100:+.0f} pts",
         with_changes(inp, margin_shift=BULL.margin_shift), f"{BULL.margin_shift * 100:+.0f} pts"),
        ("WACC", with_changes(inp, wacc=inp.wacc + BEAR.wacc_shift), f"{(inp.wacc + BEAR.wacc_shift) * 100:.2f}%",
         with_changes(inp, wacc=inp.wacc + BULL.wacc_shift), f"{(inp.wacc + BULL.wacc_shift) * 100:.2f}%"),
        ("Terminal growth", with_changes(inp, terminal_growth=inp.terminal_growth + BEAR.terminal_growth_shift),
         f"{(inp.terminal_growth + BEAR.terminal_growth_shift) * 100:.2f}%",
         with_changes(inp, terminal_growth=g_hi), f"{g_hi * 100:.2f}%"),
    ]
    if all(y.sales_to_capital is not None for y in inp.years):
        def s2c(k: float) -> DCFInputs:
            return replace(inp, years=tuple(replace(y, sales_to_capital=y.sales_to_capital * k) for y in inp.years))
        moves.append(("Sales-to-capital", s2c(1 - S2C_STEP), f"-{S2C_STEP:.0%}", s2c(1 + S2C_STEP), f"+{S2C_STEP:.0%}"))
    rows = []
    for label, lo_in, lo_d, hi_in, hi_d in moves:
        lo, hi = value(lo_in), value(hi_in)
        if lo is None or hi is None:
            continue
        rows.append({"label": label, "base": base, "low": lo, "high": hi, "low_detail": lo_d, "high_detail": hi_d})
    return sorted(rows, key=lambda r: abs(r["high"] - r["low"]), reverse=True)


# --- 8. Economic profit: the same DCF as capital plus value created above its cost ----------------------------------
def economic_profit(dcf: DCFResult, invested_capital: float) -> dict | None:
    """The DCF's enterprise value split (McKinsey's economic-profit identity) into the capital invested today, the
    present value of each forecast year's economic profit (NOPAT less a charge for capital) and the terminal value
    above the capital the forecast ends with. Capital is charged at WACC for the calendar time it is in use: the
    capital at the start of a year until the year end (only the part still to come in year 1), and the year's new
    capital from when the DCF counts it (mid-year) to the year end. The three parts add up to the EV exactly. Capital
    grows by the reinvestment the DCF counts. Each row is in money of the point where the DCF counts the year's
    profit (mid-year), so profit less charge is the economic profit. None if capital is not positive."""
    if invested_capital is None or invested_capital <= 0:
        return None
    _, end_n = _timing(dcf.inputs)
    n, w = len(dcf.years), dcf.inputs.wacc
    ic, end_prev, rows, total = invested_capital, 0.0, [], 0.0
    for t, y in enumerate(dcf.years, start=1):
        end = max(end_n - (n - t), 0.0)
        f_end, f_prev = (1 + w) ** -end, (1 + w) ** -end_prev
        k = y.counted_fcf / y.fcf if y.fcf else 1.0  # share of the year counted
        e = y.pv / y.counted_fcf if y.counted_fcf else y.discount_factor  # the year's average discount factor
        new = k * y.reinvestment
        pv_charge = (f_prev - f_end) * ic + (e - f_end) * new
        pv_ep = e * k * y.nopat - pv_charge
        rows.append({"label": y.label, "capital": ic, "nopat": k * y.nopat, "charge": pv_charge / e,
                     "ep": pv_ep / e, "return": y.nopat / ic if ic else None, "pv": pv_ep})
        total += pv_ep
        ic += new
        end_prev = end
    beyond = dcf.pv_terminal_value - (1 + w) ** -end_prev * ic
    return {"capital": invested_capital, "rows": rows, "pv_ep": total, "beyond": beyond, "capital_end": ic,
            "ev": dcf.enterprise_value, "check": invested_capital + total + beyond - dcf.enterprise_value}
