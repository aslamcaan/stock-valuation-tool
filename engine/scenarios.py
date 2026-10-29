"""Scenarios, sensitivity grids and reverse DCF (pure), all built on run_dcf."""
from __future__ import annotations

from dataclasses import dataclass, replace

from engine.dcf import DCFError, DCFInputs, DCFResult, run_dcf, with_changes


@dataclass(frozen=True)
class Scenario:
    name: str
    probability: float
    growth_shift: float = 0.0       # added to every year's revenue growth
    margin_shift: float = 0.0       # added to every year's and the terminal margin (points, so it works for losses)
    wacc_shift: float = 0.0
    terminal_growth_shift: float = 0.0

    def describe(self) -> str:
        parts = []
        if self.growth_shift:
            parts.append(f"revenue growth {self.growth_shift * 100:+.0f} points a year")
        if self.margin_shift:
            parts.append(f"operating margins {self.margin_shift * 100:+.0f} points")
        if self.wacc_shift:
            parts.append(f"WACC {self.wacc_shift * 100:+.1f} points")
        if self.terminal_growth_shift:
            parts.append(f"terminal growth {self.terminal_growth_shift * 100:+.1f} points")
        return ", ".join(parts) or "base assumptions"


DEFAULT_SCENARIOS = (
    Scenario("Bear", 0.25, growth_shift=-0.03, margin_shift=-0.03, wacc_shift=0.005, terminal_growth_shift=-0.005),
    Scenario("Base", 0.50),
    Scenario("Bull", 0.25, growth_shift=0.03, margin_shift=0.02, wacc_shift=-0.005, terminal_growth_shift=0.005),
)


@dataclass(frozen=True)
class ScenarioResult:
    scenario: Scenario
    result: DCFResult | None
    error: str | None = None

    @property
    def value_per_share(self) -> float | None:
        return self.result.value_per_share if self.result else None


def apply(inp: DCFInputs, s: Scenario, max_terminal_growth: float | None = None) -> DCFInputs:
    g = inp.terminal_growth + s.terminal_growth_shift
    if max_terminal_growth is not None:
        g = min(g, max_terminal_growth)
    return with_changes(inp, growth_shift=s.growth_shift, margin_shift=s.margin_shift,
                        wacc=inp.wacc + s.wacc_shift, terminal_growth=g)


def run_scenarios(inp: DCFInputs, scenarios=DEFAULT_SCENARIOS, max_terminal_growth: float | None = None
                  ) -> tuple[list[ScenarioResult], float | None]:
    """Each scenario's result and the probability-weighted value per share."""
    total_p = sum(s.probability for s in scenarios)
    if abs(total_p - 1) > 1e-9:
        raise ValueError(f"scenario probabilities sum to {total_p:.2f}, not 1")
    out = []
    for s in scenarios:
        try:
            out.append(ScenarioResult(s, run_dcf(apply(inp, s, max_terminal_growth))))
        except DCFError as exc:
            out.append(ScenarioResult(s, None, str(exc)))
    if any(r.result is None for r in out):
        return out, None
    return out, sum(r.scenario.probability * r.value_per_share for r in out)


def grid_wacc_growth(inp: DCFInputs, wacc_steps=(-0.01, -0.005, 0, 0.005, 0.01),
                     g_steps=(-0.01, -0.005, 0, 0.005, 0.01)) -> dict:
    """Value per share for WACC (columns) x terminal growth (rows). None where g >= WACC."""
    waccs = [inp.wacc + d for d in wacc_steps]
    gs = [inp.terminal_growth + d for d in g_steps]
    rows = []
    for g in gs:
        row = []
        for w in waccs:
            try:
                row.append(run_dcf(replace(inp, wacc=w, terminal_growth=g)).value_per_share)
            except DCFError:
                row.append(None)
        rows.append(row)
    return {"wacc": waccs, "terminal_growth": gs, "value_per_share": rows}


def grid_growth_margin(inp: DCFInputs, growth_steps=(-0.04, -0.02, 0, 0.02, 0.04),
                       margin_steps=(-0.04, -0.02, 0, 0.02, 0.04)) -> dict:
    """Value per share for revenue growth shift (rows) x operating margin shift (columns), in points."""
    rows = []
    for gs in growth_steps:
        row = []
        for ms in margin_steps:
            try:
                row.append(run_dcf(with_changes(inp, growth_shift=gs, margin_shift=ms)).value_per_share)
            except DCFError:
                row.append(None)
        rows.append(row)
    return {"growth_shift": list(growth_steps), "margin_shift": list(margin_steps), "value_per_share": rows}


def _solve(value_at, target: float, lo: float, hi: float, steps: int = 24, tol: float = 1e-6) -> float | None:
    """Root of value_at(x) = target in [lo, hi]: scan a grid for a sign change (value need not be monotonic),
    then bisect inside the first bracket. None if the price is not reachable in the range."""
    xs = [lo + (hi - lo) * k / steps for k in range(steps + 1)]
    prev_x = prev_f = None
    for x in xs:
        try:
            f = value_at(x) - target
        except DCFError:
            prev_x = prev_f = None
            continue
        if prev_f is not None and prev_f * f <= 0:
            a, fa, b = prev_x, prev_f, x
            for _ in range(100):
                m = (a + b) / 2
                try:
                    fm = value_at(m) - target
                except DCFError:  # invalid inside the bracket: settle for the bracket's midpoint
                    return m
                if abs(fm) < tol or b - a < 1e-10:
                    return m
                if fa * fm <= 0:
                    b = m
                else:
                    a, fa = m, fm
            return (a + b) / 2
        prev_x, prev_f = x, f
    return None


def reverse_dcf(inp: DCFInputs, price: float) -> dict:
    """What the share price implies, holding everything else at the base case:
    - growth: a uniform shift to every year's revenue growth (reported as the implied revenue CAGR);
    - margin: a uniform shift to every year's and the terminal operating margin (reported as the implied
      terminal margin)."""
    def by_growth(x):
        return run_dcf(with_changes(inp, growth_shift=x)).value_per_share

    def by_margin(x):
        return run_dcf(with_changes(inp, margin_shift=x)).value_per_share

    out: dict = {"base_cagr": _cagr(inp), "years": len(inp.years)}
    g = _solve(by_growth, price, -0.30, 0.60)
    if g is None:
        out["growth"] = {"solved": False, "reason": "price not reachable by changing growth alone (-30 to +60 points)"}
    else:
        out["growth"] = {"solved": True, "growth_shift": g, "implied_cagr": _cagr(with_changes(inp, growth_shift=g))}
    m = _solve(by_margin, price, -0.30, 0.40)
    base_tm = inp.terminal_margin if inp.terminal_margin is not None else inp.years[-1].operating_margin
    if m is None:
        out["margin"] = {"solved": False, "reason": "price not reachable by changing margins alone (-30 to +40 points)"}
    else:
        out["margin"] = {"solved": True, "margin_shift": m, "implied_terminal_margin": base_tm + m,
                         "base_terminal_margin": base_tm}
    out["solved"] = out["growth"]["solved"] or out["margin"]["solved"]
    return out


def _cagr(inp: DCFInputs) -> float:
    prod = 1.0
    for y in inp.years:
        prod *= 1 + y.revenue_growth
    return prod ** (1 / len(inp.years)) - 1
