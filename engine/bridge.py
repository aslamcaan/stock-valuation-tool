"""Valuation bridge (pure): from one set of DCF inputs to another, one assumption group at a time.

Used for test_grab_judgement: from the user's own model to the tool's defaults, showing the change in value
per share caused by each assumption group. The order is fixed and stated, because a bridge is path-dependent:
1. forecast horizon and revenue growth, 2. operating margin (basis and level, incl. SBC), 3. tax,
4. reinvestment method, 5. WACC, 6. terminal value, 7. timing conventions, 8. equity bridge, 9. share count.
The final step reproduces the target inputs exactly, so the steps sum to the full gap.
"""
from __future__ import annotations

from dataclasses import dataclass, replace

from engine.dcf import DCFError, DCFInputs, YearDrivers, run_dcf


@dataclass(frozen=True)
class BridgeStep:
    name: str
    description: str
    value_per_share: float | None
    change: float | None
    error: str | None = None


def _years(start: DCFInputs, end: DCFInputs, **take_from_end) -> tuple[YearDrivers, ...]:
    out = []
    for i, e in enumerate(end.years):
        s = start.years[min(i, len(start.years) - 1)]
        fields = {f: getattr(e if take_from_end.get(f) else s, f) for f in
                  ("revenue_growth", "operating_margin", "tax_rate", "sales_to_capital", "da_pct", "capex_pct",
                   "nwc_pct_of_change", "sbc_pct")}
        out.append(YearDrivers(label=e.label, **fields))
    return tuple(out)


def dcf_bridge(start: DCFInputs, end: DCFInputs, per_share_factor: float = 1.0) -> list[BridgeStep]:
    take: dict[str, bool] = {"revenue_growth": True}
    cur = replace(start, base_revenue=end.base_revenue, years=_years(start, end, **take))
    plan = [
        ("Forecast horizon and revenue growth", f"{len(start.years)} -> {len(end.years)} years; tool growth path",
         lambda c: c),
        ("Operating margin", "tool margin path and basis (GAAP operating margin: SBC is a cost)",
         lambda c: replace(c, years=_years(start, end, revenue_growth=True, operating_margin=True, sbc_pct=True),
                           conventions=replace(c.conventions, margin_basis=end.conventions.margin_basis,
                                               sbc_as_cash=end.conventions.sbc_as_cash))),
        ("Tax rate", "tool tax path and terminal tax",
         lambda c: replace(c, years=_years(start, end, revenue_growth=True, operating_margin=True, sbc_pct=True,
                                           tax_rate=True), terminal_tax_rate=end.terminal_tax_rate)),
        ("Reinvestment", f"{start.conventions.reinvestment} -> {end.conventions.reinvestment}",
         lambda c: replace(c, years=end.years, conventions=replace(c.conventions,
                                                                     reinvestment=end.conventions.reinvestment))),
        ("Discount rate (WACC)", f"{start.wacc:.2%} -> {end.wacc:.2%}", lambda c: replace(c, wacc=end.wacc)),
        ("Terminal value", f"{start.conventions.terminal} at g {start.terminal_growth:.2%} -> "
                           f"{end.conventions.terminal} at g {end.terminal_growth:.2%}"
                           + (f", terminal ROIC {end.terminal_roic:.1%}" if end.terminal_roic else ""),
         lambda c: replace(c, terminal_growth=end.terminal_growth, terminal_roic=end.terminal_roic,
                           terminal_margin=end.terminal_margin,
                           conventions=replace(c.conventions, terminal=end.conventions.terminal))),
        ("Timing conventions", f"{start.conventions.discounting}{', stub' if start.conventions.stub else ''} -> "
                               f"{end.conventions.discounting}, dated from the balance sheet and valuation date",
         lambda c: replace(c, conventions=end.conventions, timing=end.timing, end_of_final_year=end.end_of_final_year,
                           stub_fraction=end.stub_fraction)),
        ("Equity bridge", "cash, debt and other claims", lambda c: replace(c, bridge=end.bridge)),
        ("Share count", f"{start.shares:,.0f}m -> {end.shares:,.0f}m", lambda c: replace(c, shares=end.shares)),
    ]
    steps = []
    try:
        prev = run_dcf(start).value_per_share * per_share_factor
    except DCFError as exc:
        return [BridgeStep("Start", "starting model", None, None, str(exc))]
    steps.append(BridgeStep("Start", "starting model", prev, None))
    for name, desc, fn in plan:
        cur = fn(cur)
        try:
            val = run_dcf(cur).value_per_share * per_share_factor
            steps.append(BridgeStep(name, desc, val, None if prev is None else val - prev))
            prev = val
        except DCFError as exc:
            steps.append(BridgeStep(name, desc, None, None, str(exc)))
            prev = None
    return steps
