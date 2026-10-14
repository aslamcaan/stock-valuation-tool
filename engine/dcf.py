"""Unlevered DCF (pure).

Conventions are explicit so the same engine can reproduce a hand-built model and run the tool's own
defaults:
- discounting: "mid_year" (cash flows arrive mid-period) or "end_year".
- timing: either a simple stub (`stub_fraction` of year 1 still to come, discounting from today), or an
  explicit per-year `timing` of (fraction of the year's FCF counted, discount period in years). The tool
  uses explicit timing so that cash generated after the latest balance sheet is counted even when part of
  it falls before the valuation date (discounted at period 0).
- margin_basis: "gaap" operating margin (SBC already expensed) or "adjusted" (pre-SBC). With
  "adjusted" and sbc_as_cash=True, SBC is deducted as a cash cost.
- tax: no tax is paid on losses; losses inside the forecast are carried forward against later profits.
- reinvestment: "sales_to_capital" (reinvestment = change in revenue / sales-to-capital) or
  "explicit" (capex - D&A + change in working capital).
- terminal: "value_driver" (FCF_{N+1} = NOPAT_{N+1} x (1 - g / terminal ROIC), so reinvestment is
  consistent with growth) or "gordon_final_fcf" (FCF_N x (1 + g)). The Gordon value is as at one period
  before FCF_{N+1} arrives: end of year N under end-year discounting, mid-year N under mid-year discounting.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace


class DCFError(ValueError):
    """Inputs that make the DCF meaningless (e.g. terminal growth at or above WACC)."""


@dataclass(frozen=True)
class Conventions:
    discounting: str = "mid_year"
    stub: bool = True
    margin_basis: str = "gaap"
    sbc_as_cash: bool = True
    reinvestment: str = "sales_to_capital"
    terminal: str = "value_driver"


@dataclass(frozen=True)
class YearDrivers:
    label: str
    revenue_growth: float
    operating_margin: float          # EBIT / revenue on `margin_basis`
    tax_rate: float
    sales_to_capital: float | None = None
    da_pct: float | None = None      # explicit reinvestment mode
    capex_pct: float | None = None
    nwc_pct_of_change: float = 0.0   # change in NWC as % of change in revenue
    sbc_pct: float = 0.0


@dataclass(frozen=True)
class DCFInputs:
    base_label: str
    base_revenue: float
    years: tuple[YearDrivers, ...]
    wacc: float
    terminal_growth: float
    terminal_roic: float | None = None
    terminal_margin: float | None = None   # default: final-year margin
    terminal_tax_rate: float | None = None  # default: final-year tax rate
    stub_fraction: float = 1.0             # share of year 1 still to come (1.0 = full year)
    conventions: Conventions = field(default_factory=Conventions)
    bridge: tuple[tuple[str, float], ...] = ()  # (name, signed amount added to EV to reach equity)
    shares: float = 1.0                    # diluted shares (millions)
    timing: tuple[tuple[float, float, float], ...] | None = None  # per year: (share before today, share after, period)
    end_of_final_year: float | None = None  # years from valuation date to the end of the final year (with timing)


@dataclass(frozen=True)
class DCFYear:
    label: str
    revenue: float
    ebit: float
    sbc_cost: float
    taxes: float
    nopat: float
    reinvestment: float
    fcf: float               # full-year unlevered FCF
    counted_fcf: float       # the part of the year that is valued
    period: float            # discount period in years from the valuation date
    discount_factor: float
    pv: float
    da: float | None = None
    capex: float | None = None
    nwc_change: float | None = None
    loss_carryforward_used: float = 0.0


@dataclass(frozen=True)
class DCFResult:
    years: tuple[DCFYear, ...]
    terminal_fcf: float
    terminal_value: float
    terminal_period: float
    pv_terminal_value: float
    sum_pv_fcf: float
    enterprise_value: float
    bridge: tuple[tuple[str, float], ...]
    equity_value: float
    shares: float
    value_per_share: float
    tv_share_of_ev: float
    implied_exit_ebit_multiple: float | None
    inputs: DCFInputs


def _timing(inp: DCFInputs) -> tuple[list[tuple[float, float, float]], float]:
    """Per year: (share of the year's FCF already generated but not yet in the balance sheet, share still to come,
    discount period of the part still to come); plus the end of the final year in years from today."""
    conv, n = inp.conventions, len(inp.years)
    if inp.timing is not None:
        if len(inp.timing) != n or inp.end_of_final_year is None:
            raise DCFError("explicit timing needs one entry per year and the end of the final year")
        return list(inp.timing), inp.end_of_final_year
    s = inp.stub_fraction if conv.stub else 1.0
    if not 0 < s <= 1:
        raise DCFError(f"stub fraction {s} must be in (0, 1]")
    ends = [s + k for k in range(n)]
    if conv.discounting == "end_year":
        periods = ends
    elif conv.discounting == "mid_year":
        periods = [s / 2] + [e - 0.5 for e in ends[1:]]
    else:
        raise DCFError(f"unknown discounting convention {conv.discounting}")
    return [(0.0, (s if k == 0 else 1.0), t) for k, t in enumerate(periods)], ends[-1]


def run_dcf(inp: DCFInputs) -> DCFResult:
    conv = inp.conventions
    if not inp.years:
        raise DCFError("no forecast years")
    if inp.terminal_growth >= inp.wacc:
        raise DCFError(f"terminal growth {inp.terminal_growth:.2%} is at or above WACC {inp.wacc:.2%}")
    timing, end_n = _timing(inp)

    rows: list[DCFYear] = []
    prev_rev = inp.base_revenue
    losses = 0.0  # tax losses carried forward (forecast years only)
    for y, (pre, post, t) in zip(inp.years, timing):
        rev = prev_rev * (1 + y.revenue_growth)
        ebit = rev * y.operating_margin
        sbc_cost = rev * y.sbc_pct if (conv.margin_basis == "adjusted" and conv.sbc_as_cash) else 0.0
        taxable = ebit - sbc_cost
        used = 0.0
        if taxable < 0:
            losses += -taxable
            taxes = 0.0
        else:
            used = min(losses, taxable)
            losses -= used
            taxes = (taxable - used) * y.tax_rate
        nopat = taxable - taxes
        da = capex = nwc = None
        if conv.reinvestment == "explicit":
            if y.da_pct is None or y.capex_pct is None:
                raise DCFError(f"{y.label}: explicit reinvestment needs D&A and capex % of revenue")
            da, capex = rev * y.da_pct, rev * y.capex_pct
            nwc = (rev - prev_rev) * y.nwc_pct_of_change
            reinvest = capex - da + nwc
        elif conv.reinvestment == "sales_to_capital":
            if not y.sales_to_capital or y.sales_to_capital <= 0:
                raise DCFError(f"{y.label}: sales-to-capital ratio must be positive")
            reinvest = (rev - prev_rev) / y.sales_to_capital
        else:
            raise DCFError(f"unknown reinvestment mode {conv.reinvestment}")
        fcf = nopat - reinvest
        counted = fcf * (pre + post)
        df = (1 + inp.wacc) ** -t
        rows.append(DCFYear(y.label, rev, ebit, sbc_cost, taxes, nopat, reinvest, fcf, counted, t, df,
                            fcf * (pre + post * df), da, capex, nwc, used))
        prev_rev = rev

    last, g, w = rows[-1], inp.terminal_growth, inp.wacc
    if conv.terminal == "gordon_final_fcf":
        tv_fcf = last.fcf * (1 + g)
    elif conv.terminal == "value_driver":
        roic = inp.terminal_roic
        if roic is None or roic <= 0:
            raise DCFError("value-driver terminal value needs a positive terminal ROIC")
        if g > roic:
            raise DCFError(f"terminal growth {g:.2%} above terminal ROIC {roic:.2%} needs reinvestment above 100%")
        y_last = inp.years[-1]
        margin = inp.terminal_margin if inp.terminal_margin is not None else y_last.operating_margin
        tax = inp.terminal_tax_rate if inp.terminal_tax_rate is not None else y_last.tax_rate
        rev_t = last.revenue * (1 + g)
        sbc_t = rev_t * y_last.sbc_pct if (conv.margin_basis == "adjusted" and conv.sbc_as_cash) else 0.0
        pre_tax = rev_t * margin - sbc_t
        if pre_tax <= 0:
            raise DCFError(f"terminal operating profit is not positive (margin {margin:.1%}): a steady-state "
                           f"value cannot be computed")
        nopat_t = pre_tax * (1 - tax)
        tv_fcf = nopat_t * (1 - g / roic)
    else:
        raise DCFError(f"unknown terminal method {conv.terminal}")
    tv = tv_fcf / (w - g)
    t_tv = end_n - (0.5 if conv.discounting == "mid_year" else 0.0)
    pv_tv = tv * (1 + w) ** -t_tv
    sum_pv = sum(r.pv for r in rows)
    ev = sum_pv + pv_tv
    equity = ev + sum(v for _, v in inp.bridge)
    if inp.shares <= 0:
        raise DCFError("share count must be positive")
    return DCFResult(tuple(rows), tv_fcf, tv, t_tv, pv_tv, sum_pv, ev, inp.bridge, equity, inp.shares,
                     equity / inp.shares, pv_tv / ev if ev else float("nan"),
                     tv / last.ebit if last.ebit > 0 else None, inp)


def with_changes(inp: DCFInputs, growth_shift: float = 0.0, margin_shift: float = 0.0, margin_scale: float = 1.0,
                 wacc: float | None = None, terminal_growth: float | None = None) -> DCFInputs:
    """Copy of the inputs with uniform shifts (used for scenarios, sensitivities and the reverse DCF)."""
    years = tuple(replace(y, revenue_growth=y.revenue_growth + growth_shift,
                          operating_margin=y.operating_margin * margin_scale + margin_shift) for y in inp.years)
    tm = inp.terminal_margin
    return replace(inp, years=years,
                   terminal_margin=None if tm is None else tm * margin_scale + margin_shift,
                   wacc=inp.wacc if wacc is None else wacc,
                   terminal_growth=inp.terminal_growth if terminal_growth is None else terminal_growth)
