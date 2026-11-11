"""Forecast assumptions (pure): consensus blending and stage-based fades (PROMPT.md 4b and 4c).

For each driver the plan records history | consensus | industry | chosen, where the chosen value came from
and a confidence level. Rules:
- Years 1-2: analyst consensus if at least 3 analysts cover the year (FMP publishes the mean, not the
  median; this is stated on the row). Otherwise history.
- Later years fade from the year-2 value toward the industry median, by stage:
  early / high growth: 10 years (years 3-5 toward the industry rate, 6-10 toward terminal growth);
  mature, cyclical, declining: 5 years toward terminal growth.
- Growth: every year is capped at the company's best year in the last decade, and a company growing faster than
  its industry fades monotonically (no re-acceleration). Raw analyst consensus is used only in the bull scenario.
- Margins: early -> ramp to the industry (mature-peer) margin; high / mature growth -> close half the gap to
  the industry margin; mature stable -> 5-year average; cyclical -> a straight-line fade from year 3 to the
  mid-cycle target (half way between the median margin and the 90th percentile of the years on file).
- Tax: the latest effective rate phases up to the marginal (statutory) rate by year 5 (low effective rates last
  a few years, not for ever); the marginal rate applies in the terminal value.
- Reinvestment: sales-to-capital (company history, else industry).
Every number is a Value; per-year paths are plain floats derived from those Values by the rules above.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from statistics import mean

from engine.dates import years_later
from engine.classify import CYCLICAL, DECLINING, EARLY, HIGH_GROWTH, MATURE_GROWTH, MATURE_STABLE
from engine.dcf import Conventions, DCFInputs, YearDrivers
from engine.flags import AMBER, INFO, Flag
from engine.model import Historicals
from engine.values import RATIO, Value

HORIZON = {EARLY: 10, HIGH_GROWTH: 10, CYCLICAL: 7}  # a cyclical's margin fade needs 4-5 years before it settles
TAX_PHASE_YEARS = 5          # the effective tax rate reaches the marginal rate in this forecast year
CYCLICAL_ROIC_SPREAD = 0.04  # terminal ROIC of a cyclical: WACC plus this (3-5 points; no durable pricing power assumed)
DEFAULT_HORIZON = 5
MIN_ANALYSTS = 3
CONSENSUS_BASIS_GAP = 0.03
HISTORY_GROWTH_BOUNDS = (-0.15, 0.30)    # latest-year growth used without consensus is clipped to this range
CYCLICAL_GROWTH_BOUNDS = (-0.05, 0.10)   # cyclicals use their long-run CAGR, clipped to this range
DEFAULT_TERMINAL_GROWTH = 0.025


@dataclass
class ConsensusYear:
    fiscal_year_end: date
    revenue: float | None
    revenue_low: float | None
    revenue_high: float | None
    ebit: float | None
    analysts: int
    source: str
    fetched_at: str | None = None


@dataclass
class DriverRow:
    name: str
    label: str
    history: Value | None
    consensus: Value | None
    industry: Value | None
    chosen: Value
    path: list[float]
    source: str
    confidence: str
    note: str | None = None


@dataclass
class ForecastPlan:
    base_label: str
    base_revenue: Value
    labels: list[str]                 # all forecast years from the base year
    skipped: list[str]                # completed but unreported years (not discounted)
    stub_fraction: float
    valuation_date: date
    drivers: dict[str, DriverRow]
    terminal_growth: Value
    terminal_roic: Value
    stage: str
    year_ends: list[date] = field(default_factory=list)
    base_end: date | None = None
    flags: list[Flag] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    raw_growth_path: list[float] | None = None   # uncapped analyst-consensus path: the bull scenario's input

    def path(self, name: str) -> list[float]:
        return self.drivers[name].path


def _lerp(a: float, b: float, n: int) -> list[float]:
    """n values stepping from a toward b, ending at b."""
    return [a + (b - a) * (k + 1) / n for k in range(n)] if n > 0 else []


def fade_growth(path: list[float], cap: float | None, floor_rate: float) -> list[float]:
    """The base-case growth path: no year above `cap` (the company's best year), and while growth is above
    `floor_rate` (the industry rate) it only falls, never re-accelerates."""
    out: list[float] = []
    for x in path:
        if cap is not None and x > cap:
            x = cap
        if out and out[-1] >= floor_rate:
            x = min(x, out[-1])
        out.append(x)
    return out


def _fy_ends(last_end: date, count: int) -> list[date]:
    return [years_later(last_end, k + 1) for k in range(count)]


def _v(x: float, note: str, source: str = "calculated") -> Value:
    return Value(x, None, RATIO, "forecast", source, note=note)


def build_plan(h: Historicals, stage: str, *, valuation_date: date, current_margin: Value | None,
               consensus: list[ConsensusYear], industry_margin: Value | None, industry_growth: Value | None,
               industry_sales_to_capital: Value | None, effective_tax: Value | None, marginal_tax: Value,
               risk_free: Value, wacc: float, roic: Value | None, mid_cycle_margin: float | None,
               five_year_avg_margin: float | None, overrides: dict | None = None,
               cycle_target_margin: float | None = None) -> ForecastPlan:
    overrides = overrides or {}
    fy = h.fy_labels
    base = fy[-1]
    base_period = next(p for p in h.periods if p.label == base)
    base_rev = h.get("revenue", base)
    horizon = HORIZON.get(stage, DEFAULT_HORIZON)

    # forecast years: skip any fiscal year that has already ended but is not yet reported
    ends = _fy_ends(base_period.end, horizon + 3)
    skipped_n = sum(1 for e in ends if e <= valuation_date)
    all_ends = ends[:skipped_n + horizon]
    labels = [f"FY{(e.year - 1) if (e.month == 1 and e.day <= 7) else e.year}E" for e in all_ends]
    first = all_ends[skipped_n]
    year_len = (first - (all_ends[skipped_n - 1] if skipped_n else base_period.end)).days
    stub = max(min((first - valuation_date).days / year_len, 1.0), 1 / year_len)
    n = len(labels)
    flags: list[Flag] = []
    notes: list[str] = []
    if skipped_n:
        notes.append(f"{', '.join(labels[:skipped_n])} has ended but is not yet reported: it is forecast, and the "
                     f"part of its cash flow after the latest balance sheet is counted undiscounted.")

    # --- terminal growth -------------------------------------------------------------------------
    g_default = 0.0 if stage == DECLINING else min(DEFAULT_TERMINAL_GROWTH, risk_free.value)
    g = overrides.get("terminal_growth", g_default)
    g_val = Value(g, None, RATIO, "terminal", "user override" if "terminal_growth" in overrides else "rule",
                  note="declining: terminal growth 0%" if stage == DECLINING else
                  f"min({DEFAULT_TERMINAL_GROWTH:.1%}, risk-free {risk_free.value:.2%})")

    # --- consensus mapped to forecast years ---------------------------------------------------------
    cons_by_label: dict[str, ConsensusYear] = {}
    for c in consensus:
        for lab, e in zip(labels, all_ends):
            if abs((c.fiscal_year_end - e).days) <= 20:
                cons_by_label[lab] = c

    # --- revenue growth ------------------------------------------------------------------------------
    growth_hist = []
    rev = [(p, h.v("revenue", p)) for p in fy if h.v("revenue", p)]
    for (p0, r0), (p1, r1) in zip(rev, rev[1:]):
        if r0 > 0:
            growth_hist.append((p1, r1 / r0 - 1))
    hist_growth = Value(growth_hist[-1][1], None, RATIO, growth_hist[-1][0], "calculated",
                        formula="latest fiscal-year revenue growth") if growth_hist else None
    best_hist = max((x for _, x in growth_hist[-10:]), default=None)
    cons_growth, prev_rev, cons_detail = [], base_rev.value, []
    for lab in labels[:n - 1]:  # every year with enough analysts; the last explicit year converges on terminal growth
        c = cons_by_label.get(lab)
        if c and c.revenue and c.analysts >= MIN_ANALYSTS and prev_rev:
            cons_growth.append(c.revenue / prev_rev - 1)
            cons_detail.append(f"{lab}: {c.revenue:,.0f} ({c.analysts} analysts, range {c.revenue_low:,.0f}-"
                               f"{c.revenue_high:,.0f})")
            prev_rev = c.revenue
        else:
            break
    use_cons = len(cons_growth) >= skipped_n + 2
    ind_g = industry_growth.value if industry_growth is not None else g
    ind_g = min(max(ind_g, g), 0.20)
    if use_cons:
        first2 = cons_growth
        k_cons = len(first2) - skipped_n
        g_source = (f"analyst consensus (FMP mean; median not published) for years 1-{k_cons}" if k_cons > 1 else
                    "analyst consensus (FMP mean; median not published) for year 1")
        cons_v = Value(first2[skipped_n], None, RATIO, labels[skipped_n], "FMP analyst estimates",
                       note="; ".join(cons_detail))
        disp = [(c.revenue_high - c.revenue_low) / c.revenue
                for c in (cons_by_label[x] for x in labels[skipped_n:skipped_n + 2])
                if c.revenue_high and c.revenue_low and c.revenue]
        n_an = min(cons_by_label[x].analysts for x in labels[:skipped_n + 2])
        confidence = "High" if n_an >= 5 and disp and max(disp) <= 0.10 else "Medium"
        if best_hist is not None and max(first2) > best_hist:
            flags.append(Flag(AMBER, "consensus_above_history", "Consensus growth above best historical year",
                              f"Consensus revenue growth {max(first2):.1%} exceeds the company's best year in the "
                              f"last decade ({best_hist:.1%}). The base case caps every year at that best year and "
                              f"lets growth fade without re-accelerating; the raw consensus is the bull case only.",
                              labels[0],
                              {"consensus_growth": max(first2), "best_historical_growth": best_hist}))
    else:
        if stage == CYCLICAL and len(rev) >= 4 and rev[0][1] > 0 and rev[-1][1] > 0:
            years = len(rev) - 1
            long_run = (rev[-1][1] / rev[0][1]) ** (1 / years) - 1
            h1 = min(max(long_run, CYCLICAL_GROWTH_BOUNDS[0]), CYCLICAL_GROWTH_BOUNDS[1])
            g_source = (f"history: {years}-year revenue CAGR {long_run:.1%}"
                        + (f", capped at {h1:.0%}" if h1 != long_run else "")
                        + " for years 1-2 (a cyclical's latest year is not extrapolated); no consensus")
        elif stage in (MATURE_GROWTH, MATURE_STABLE, DECLINING) and len(rev) >= 4 and rev[-4][1] > 0 and rev[-1][1] > 0:
            # one year of a mature company's revenue is noisy (currency, disposals such as refranchising): use 3 years
            raw_h = (rev[-1][1] / rev[-4][1]) ** (1 / 3) - 1
            h1 = min(max(raw_h, HISTORY_GROWTH_BOUNDS[0]), HISTORY_GROWTH_BOUNDS[1])
            g_source = (f"history (3-year revenue CAGR {rev[-4][0]}-{rev[-1][0]} {raw_h:.1%}"
                        + (f", capped at {h1:.0%}" if h1 != raw_h else "")
                        + ") for years 1-2: fewer than 3 analysts or no consensus data")
        else:
            raw_h = hist_growth.value if hist_growth else ind_g
            h1 = min(max(raw_h, HISTORY_GROWTH_BOUNDS[0]), HISTORY_GROWTH_BOUNDS[1])
            g_source = ("history (latest fiscal-year growth" + (f" {raw_h:.1%}, capped at {h1:.0%}" if h1 != raw_h else "")
                        + ") for years 1-2: fewer than 3 analysts or no consensus data")
        first2 = [h1] * (skipped_n + 2)
        cons_v = None
        confidence = "Low" if stage in (EARLY, CYCLICAL) else "Medium"
    y2, k = first2[-1], len(first2)  # k years set by consensus or history; the rest ease towards terminal growth
    if horizon == 10 and k < skipped_n + 5:
        # 5 explicit years (easing halfway to the industry rate for high growth, to it otherwise), then 5 fade years
        mid = y2 + 0.5 * (ind_g - y2) if stage == HIGH_GROWTH else ind_g
        tail = _lerp(y2, mid, skipped_n + 5 - k) + _lerp(mid, g, horizon - 5)
    else:
        tail = _lerp(y2, g, n - k)
    growth_path = first2 + tail
    growth_path = growth_path[:n]
    raw_growth_path = list(growth_path) if use_cons else None
    cap = max(best_hist, ind_g) if best_hist is not None and len(growth_hist) >= 3 else None
    faded = fade_growth(growth_path, cap, ind_g)
    if any(abs(a - b) > 1e-9 for a, b in zip(faded, growth_path)):
        capped = cap is not None and max(growth_path) > cap + 1e-9
        g_source += ("; " + (f"no year above the company's best year in the last decade ({best_hist:.1%}), and "
                             if capped else "") + "growth above the industry rate only fades, never re-accelerates"
                     + ("; the raw consensus path is used in the bull case only" if use_cons else ""))
    if raw_growth_path is not None and all(abs(a - b) <= 1e-9 for a, b in zip(raw_growth_path, faded)):
        raw_growth_path = None  # nothing was changed: the bull case needs no separate path
    growth_path = faded
    if "revenue_growth" in overrides:
        growth_path = list(overrides["revenue_growth"])[:n] + growth_path[len(overrides["revenue_growth"]):]
        g_source = "user override"
        raw_growth_path = None
    drivers = {"revenue_growth": DriverRow(
        "revenue_growth", "Revenue growth", hist_growth, cons_v,
        Value(ind_g, None, RATIO, "industry", industry_growth.source if industry_growth else "terminal growth",
              note=(industry_growth.note if industry_growth else None)) if industry_growth else None,
        _v(growth_path[skipped_n], f"year 1 ({labels[skipped_n]})", "chosen"), growth_path, g_source, confidence)}

    # --- operating margin ---------------------------------------------------------------------------
    cur_m = current_margin.value if current_margin is not None else 0.0
    cons_m = []
    for lab in labels[:skipped_n + 2]:
        c = cons_by_label.get(lab)
        if c and c.ebit is not None and c.revenue and c.analysts >= MIN_ANALYSTS:
            cons_m.append(c.ebit / c.revenue)
    ind_m = industry_margin.value if industry_margin is not None else cur_m
    if len(cons_m) >= skipped_n + 2:
        raw = cons_m[:skipped_n + 2]
        m_cons = Value(raw[skipped_n], None, RATIO, labels[skipped_n], "FMP analyst estimates",
                       note="consensus EBIT / consensus revenue")
        m_conf = "Medium"
        if abs(raw[0] - cur_m) > CONSENSUS_BASIS_GAP:
            # consensus EBIT is on a different (usually adjusted) basis: keep GAAP, apply consensus changes only
            m12 = [cur_m + (x - raw[0]) for x in raw]
            m_source = (f"current GAAP margin plus the consensus margin change (consensus EBIT margin "
                        f"{raw[0]:.1%} is more than {CONSENSUS_BASIS_GAP:.0%} points from GAAP {cur_m:.1%}: "
                        f"different basis)")
            flags.append(Flag(INFO, "consensus_basis", "Consensus EBIT on a different basis",
                              f"Consensus EBIT margin {raw[0]:.1%} vs GAAP operating margin {cur_m:.1%}: consensus is "
                              f"probably adjusted (e.g. excludes SBC or amortisation). Only its year-on-year change "
                              f"is used.", labels[0], {"consensus_margin": raw[0], "gaap_margin": cur_m}))
        else:
            m12 = raw
            m_source = "analyst consensus EBIT / revenue (FMP mean) for years 1-2"
    else:
        m12 = [cur_m] * (skipped_n + 2)
        m_source = "current operating margin for years 1-2 (no consensus EBIT)"
        m_cons = None
        m_conf = "Low" if stage in (EARLY, CYCLICAL) else "Medium"
    my2 = m12[-1]
    rest = n - len(m12)
    if stage == EARLY and my2 > ind_m:
        # already above the industry aggregate (which includes loss-makers): scale does not compress margins, so
        # hold the year-2 margin rather than ramping down while revenue grows
        target, why = my2, "held at the year-2 margin (already above the industry margin)"
        m_tail = [target] * rest
    elif stage == EARLY:
        target, why = ind_m, "ramps to the industry margin (mature peers)"
        m_tail = _lerp(my2, target, rest)
    elif stage == CYCLICAL and (cycle_target_margin is not None or mid_cycle_margin is not None):
        target = cycle_target_margin if cycle_target_margin is not None else mid_cycle_margin
        why = ("fades in a straight line from year 3 to the mid-cycle target (between the median and the "
               "90th-percentile margin of the years on file, up to 10: half way, or placed by the price deck where "
               "one is shown), so there is no cliff")
        m_tail = _lerp(my2, target, rest)
    elif stage == MATURE_STABLE and five_year_avg_margin is not None:
        target, why = five_year_avg_margin, "returns to the 5-year median margin (history trend)"
        m_tail = _lerp(my2, target, rest)
    elif stage == DECLINING and my2 <= 0:
        # a going concern cannot lose money in perpetuity: a loss-making decliner either recovers or is liquidated,
        # so the margin reverts (to its own mid-cycle level where there is one, else half way to the industry)
        if mid_cycle_margin is not None and mid_cycle_margin > 0:
            target, why = mid_cycle_margin, ("reverts to the average margin of the years on file, up to 10 (a non-positive margin cannot be "
                                             "held in perpetuity by a going concern)")
        else:
            target, why = my2 + 0.5 * (ind_m - my2), ("closes half the gap to the industry margin (a non-positive "
                                                     "margin cannot be held in perpetuity by a going concern)")
        m_tail = _lerp(my2, target, rest)
    elif stage == DECLINING:
        target, why = my2, "held at the year-2 margin"
        m_tail = [target] * rest
    else:
        target, why = my2 + 0.5 * (ind_m - my2), "closes half the gap to the industry margin (mean reversion)"
        m_tail = _lerp(my2, target, rest)
    if "target_margin" in overrides:
        target, why = overrides["target_margin"], "user override"
        m_tail = _lerp(my2, target, rest)
    margin_path = m12 + m_tail
    if "margin_shift" in overrides:  # news impact: temporary margin change per year, on top of the path
        shift = list(overrides["margin_shift"])
        margin_path = [m + (shift[k] if k < len(shift) else 0.0) for k, m in enumerate(margin_path)]
        m_source += "; news adjustment applied"
    drivers["operating_margin"] = DriverRow(
        "operating_margin", "Operating margin", current_margin, m_cons, industry_margin,
        _v(target, f"target margin: {why}", "chosen"), margin_path, f"{m_source}; then {why}", m_conf)

    # --- tax ---------------------------------------------------------------------------------------------
    t0 = effective_tax.value if effective_tax is not None and 0 <= effective_tax.value <= 0.40 else marginal_tax.value
    tax_path = []
    for k in range(n):
        yr = k - skipped_n + 1  # forecast year, 1 = the first year not yet reported
        frac = 0.0 if yr <= 1 else min(1.0, (yr - 1) / (TAX_PHASE_YEARS - 1))
        tax_path.append(t0 + (marginal_tax.value - t0) * frac if t0 < marginal_tax.value else t0)
    drivers["tax_rate"] = DriverRow("tax_rate", "Tax rate", effective_tax, None, marginal_tax,
                                    _v(marginal_tax.value, "marginal (statutory) rate in the terminal value", "chosen"),
                                    tax_path, f"latest effective rate in year 1, rising in a straight line to the "
                                    f"marginal (statutory) rate by year {TAX_PHASE_YEARS}; the marginal rate applies "
                                    "in the terminal value", "Medium")

    # --- reinvestment: sales-to-capital ----------------------------------------------------------------
    s2c_hist = _sales_to_capital(h)
    if "sales_to_capital" in overrides:
        s2c, s2c_src = overrides["sales_to_capital"], "user override"
    elif s2c_hist is not None:
        s2c, s2c_src = s2c_hist.value, "company history (revenue / invested capital, 3-year average)"
    elif industry_sales_to_capital is not None:
        s2c, s2c_src = industry_sales_to_capital.value, "industry (Damodaran)"
    else:
        s2c, s2c_src = 1.5, "default 1.5 (no company or industry data)"
    drivers["sales_to_capital"] = DriverRow("sales_to_capital", "Sales-to-capital", s2c_hist, None,
                                            industry_sales_to_capital, _v(s2c, s2c_src, "chosen"), [s2c] * n,
                                            s2c_src, "Medium" if s2c_hist else "Low")

    # --- terminal ROIC --------------------------------------------------------------------------------
    if "terminal_roic" in overrides:
        t_roic = Value(overrides["terminal_roic"], None, RATIO, "terminal", "user override")
    elif roic is not None and roic.value is not None and roic.value > wacc:
        t_roic = Value(wacc + 0.5 * (min(roic.value, 0.40) - wacc), None, RATIO, "terminal", "rule",
                       note=f"halfway between WACC {wacc:.1%} and current ROIC {min(roic.value, 0.40):.1%} "
                            f"(capped at 40%): some competitive advantage persists")
    else:
        t_roic = Value(wacc, None, RATIO, "terminal", "rule",
                       note="terminal ROIC = WACC: no excess returns in steady state")
    if stage == CYCLICAL and "terminal_roic" not in overrides and t_roic.value > wacc + CYCLICAL_ROIC_SPREAD:
        t_roic = Value(wacc + CYCLICAL_ROIC_SPREAD, None, RATIO, "terminal", "rule",
                       note=f"cyclical: WACC {wacc:.1%} plus {CYCLICAL_ROIC_SPREAD * 100:.0f} points (a cyclical's "
                            f"returns do not stay at their peak; no durable pricing power assumed)")
    if t_roic.value <= g:
        t_roic = Value(g + 0.02, None, RATIO, "terminal", "rule", note="raised to terminal growth + 2 points")

    return ForecastPlan(base, base_rev, labels, labels[:skipped_n], stub, valuation_date, drivers, g_val, t_roic,
                        stage, list(all_ends), base_period.end, flags, notes, raw_growth_path)


def _sales_to_capital(h: Historicals) -> Value | None:
    vals = []
    for p in h.fy_labels[-3:]:
        rev = h.v("revenue", p)
        eq, debt, cash = h.v("total_equity", p), h.v("debt_for_valuation", p), h.v("cash_and_investments", p)
        if None in (rev, eq, debt, cash):
            continue
        inv = h.non_operating_investments(p)
        ic = eq + debt - cash - (h.v("goodwill", p) or 0.0) - (h.v("intangibles", p) or 0.0) - (inv.value if inv else 0.0)
        if ic > 0:
            vals.append(rev / ic)
    if not vals:
        return None
    x = mean(vals)
    if not 0.3 <= x <= 8:
        return None
    return Value(x, None, "x", f"{h.fy_labels[-len(vals)]}-{h.fy_labels[-1]}", "calculated",
                 formula="average of revenue / operating invested capital (equity + debt for valuation - cash - "
                         "goodwill - acquired intangibles - long-term investments valued in the equity bridge) over up to 3 years: "
                         "organic growth does not buy goodwill or stakes in other companies")


YEAR = 365.25


def year_timing(start: date, end: date, balance_sheet: date, valuation: date, mid_year: bool
                ) -> tuple[float, float, float]:
    """(share of the year's FCF generated after the balance sheet but before today, share still to come,
    discount period of the part still to come in years).

    Cash generated before the latest balance sheet is already in it, so it is not counted. Cash generated
    between the balance sheet and today is counted undiscounted. The rest is discounted to its midpoint
    (mid-year) or to the year end (end-year)."""
    length = (end - start).days or 1
    c0 = max(start, balance_sheet)
    if c0 >= end:
        return 0.0, 0.0, 0.0
    pre = max(0, (min(end, valuation) - c0).days) / length
    post_start = max(c0, valuation)
    post = max(0, (end - post_start).days) / length
    span = (end - post_start).days
    t = ((post_start - valuation).days + (span / 2 if mid_year else span)) / YEAR if post else 0.0
    return pre, post, t


def to_dcf_inputs(plan: ForecastPlan, wacc: float, bridge: tuple[tuple[str, float], ...], shares: float,
                  balance_sheet_date: date | None = None, conventions: Conventions | None = None) -> DCFInputs:
    """All forecast years from the base year, timed from the actual dates (see year_timing)."""
    conv = conventions or Conventions()
    bs = balance_sheet_date or plan.base_end
    years, timing, start = [], [], plan.base_end
    for i, end in enumerate(plan.year_ends):
        years.append(YearDrivers(label=plan.labels[i], revenue_growth=plan.path("revenue_growth")[i],
                                 operating_margin=plan.path("operating_margin")[i], tax_rate=plan.path("tax_rate")[i],
                                 sales_to_capital=plan.path("sales_to_capital")[i]))
        timing.append(year_timing(start, end, bs, plan.valuation_date, conv.discounting == "mid_year"))
        start = end
    return DCFInputs(base_label=plan.base_label, base_revenue=plan.base_revenue.value, years=tuple(years), wacc=wacc,
                     terminal_growth=plan.terminal_growth.value, terminal_roic=plan.terminal_roic.value,
                     terminal_tax_rate=plan.drivers["tax_rate"].chosen.value,
                     conventions=conv, bridge=bridge, shares=shares, timing=tuple(timing),
                     end_of_final_year=(plan.year_ends[-1] - plan.valuation_date).days / YEAR)


__all__ = ["ConsensusYear", "DriverRow", "ForecastPlan", "build_plan", "to_dcf_inputs"]
