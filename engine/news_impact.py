"""News impact arithmetic (pure Python): reprice the valuation for proposed driver changes, measure the stock's
abnormal return since a news item, and compare the two ("priced in?").

The base valuation is never changed: every news effect is computed on a copy of the engine inputs, and the
news-adjusted fair value is shown next to the base fair value. Comps and historical multiples are market-based,
so news moves only the DCF leg (or the sum of the parts, scaled by the DCF's change) before the same blend.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace

from engine.flags import HARD_STOP
from engine.valuation import value_company
from engine.verdict import blend

DRIVERS = ["revenue_growth", "operating_margin", "sales_to_capital", "wacc", "terminal_growth",
           "scenario_probability", "none"]
DRIVER_LABEL = {"revenue_growth": "Revenue growth", "operating_margin": "Operating margin",
                "sales_to_capital": "Sales-to-capital (capex)", "wacc": "WACC", "terminal_growth": "Terminal growth",
                "scenario_probability": "Bull/bear scenario probability", "none": "No model driver"}
# Largest change code accepts from one news item (units as proposed: percentage points; x for sales-to-capital).
# A bigger proposal is not an honest estimate from a news story, so it is shown as qualitative only.
BOUNDS = {"revenue_growth": 10.0, "operating_margin": 5.0, "sales_to_capital": 1.0, "wacc": 1.5,
          "terminal_growth": 0.5, "scenario_probability": 25.0}
UNIT = {"sales_to_capital": "x", "scenario_probability": "points (bear to bull)"}
MIN_PROB = 0.05
NOISE = 0.01  # abnormal moves under 1% are treated as no move


class RepriceError(Exception):
    """The model cannot be valued with the proposed changes (e.g. terminal growth at or above WACC)."""


@dataclass
class Change:
    driver: str
    change: float      # percentage points (x for sales-to-capital; points moved from bear to bull for probability)
    years: int = 1     # years affected, for revenue growth and margin


@dataclass
class Repriced:
    fair_value: float | None
    dcf_value: float | None
    year1_nopat_per_share: float | None
    verdict: str | None
    notes: list[str] = field(default_factory=list)


def check_change(c: Change) -> str | None:
    """None if code accepts the proposed change; otherwise why it is shown as qualitative only."""
    if c.driver not in BOUNDS:
        return "no model driver"
    if c.change == 0:
        return "no change proposed"
    if abs(c.change) > BOUNDS[c.driver]:
        unit = UNIT.get(c.driver, "points")
        return (f"proposed change of {c.change:+g} {unit} is beyond the {BOUNDS[c.driver]:g} {unit} a single news item "
                f"can plausibly justify")
    return None


def capped(changes: list[Change]) -> tuple[list[Change], list[str]]:
    """Several items on one driver are summed; the total is held to the same bound as one item, so stacked stories
    about one event cannot move the model further than the event itself could."""
    totals: dict[str, float] = {}
    for c in changes:
        totals[c.driver] = totals.get(c.driver, 0.0) + c.change
    out, notes = [], []
    for c in changes:
        t, b = totals[c.driver], BOUNDS.get(c.driver)
        if b is not None and abs(t) > b:
            factor = b / abs(t)
            out.append(Change(c.driver, c.change * factor, c.years))
            note = (f"combined {c.driver.replace('_', ' ')} change of {t:+g} capped at {b:g} "
                    f"{UNIT.get(c.driver, 'points')}")
            if note not in notes:
                notes.append(note)
        else:
            out.append(c)
    return out, notes


def first_forecast_index(report) -> int:
    """Index of the first forecast year in plan paths: years already ended but not yet reported come first."""
    return len(report.valuation.plan.skipped)


def overrides_for(report, changes: list[Change]) -> tuple[dict, float]:
    """Engine overrides for a set of accepted changes (summed per driver and year), plus the probability shift.
    Shifts start at the first forecast year (after any ended but unreported year) and build on the values the
    model actually used, including the user's own overrides."""
    v = report.valuation
    plan = v.plan
    ov0 = report.inputs.overrides or {}
    n = len(plan.path("revenue_growth"))
    k0 = first_forecast_index(report)
    ov: dict = {}
    g_shift = [0.0] * n
    m_shift = [0.0] * n
    prob = 0.0
    for c in changes:
        years = max(1, min(int(c.years or 1), n - k0))
        if c.driver == "revenue_growth":
            for k in range(k0, k0 + years):
                g_shift[k] += c.change / 100
        elif c.driver == "operating_margin":
            for k in range(k0, k0 + years):
                m_shift[k] += c.change / 100
        elif c.driver == "sales_to_capital":
            ov["sales_to_capital"] = ov.get("sales_to_capital", plan.drivers["sales_to_capital"].chosen.value) + c.change
        elif c.driver == "wacc":
            ov["wacc"] = ov.get("wacc", ov0.get("wacc", v.wacc.wacc.value)) + c.change / 100
        elif c.driver == "terminal_growth":
            ov["terminal_growth"] = ov.get("terminal_growth", plan.terminal_growth.value) + c.change / 100
        elif c.driver == "scenario_probability":
            prob += c.change / 100
    if any(g_shift):
        ov["revenue_growth"] = [g + s for g, s in zip(plan.path("revenue_growth"), g_shift)]
    if any(m_shift):
        base_shift = list(ov0.get("margin_shift") or [])
        ov["margin_shift"] = [m + (base_shift[k] if k < len(base_shift) else 0.0) for k, m in enumerate(m_shift)]
    return ov, prob


def _scenario_value(v, prob_shift: float) -> tuple[float | None, list[str]]:
    """Probability-weighted DCF value with `prob_shift` moved from the bear to the bull scenario."""
    res = {s.scenario.name: (s.scenario.probability, s.result.value_per_share) for s in v.scenarios if s.result}
    if not prob_shift:
        return v.scenario_value, []
    if "Bear" not in res or "Bull" not in res:
        return v.scenario_value, ["bull or bear scenario not available: probability shift not applied"]
    probs = {k: p for k, (p, _) in res.items()}
    shift = max(-(probs["Bull"] - MIN_PROB), min(prob_shift, probs["Bear"] - MIN_PROB))
    notes = [] if shift == prob_shift else [f"probability shift limited to {shift:+.0%} (each scenario keeps at least "
                                            f"{MIN_PROB:.0%})"]
    probs["Bull"] += shift
    probs["Bear"] -= shift
    total = sum(probs.values())
    return sum(probs[k] * res[k][1] for k in res) / total, notes


def reprice(report, overrides: dict, prob_shift: float = 0.0) -> Repriced:
    """The report's valuation with extra engine overrides; comps and history legs held as they are.
    Raises engine errors (e.g. terminal growth at or above WACC) for the caller to report."""
    base_ei = report.inputs
    ei = replace(base_ei, overrides={**(base_ei.overrides or {}), **overrides})
    v = value_company(ei)
    # A changed model that breaks the DCF must not quietly fall back to comps: that is not a news effect.
    stops = [f for f in v.flags if f.level == HARD_STOP and
             not any(b.code == f.code for b in report.valuation.flags if b.level == HARD_STOP)]
    if stops:
        raise RepriceError("; ".join(f"{f.title}: {f.message}" for f in stops))
    if report.valuation.dcf is not None and (v.dcf is None or v.scenario_value is None):
        raise RepriceError("the DCF or one of its scenarios cannot be computed with this change")
    notes: list[str] = []
    scen, extra = _scenario_value(v, prob_shift)
    notes += extra
    dcf_v = None if getattr(v, "model_fit_failed", False) else v.per_us_share(scen)
    comps = report.verdict.components
    sotp_v = None
    if v.sotp.applicable:
        base_dcf = report.valuation.per_us_share(report.valuation.scenario_value)
        base_sotp = report.valuation.per_us_share(report.valuation.sotp.value_per_share)
        if base_dcf and dcf_v is not None and base_sotp is not None:
            sotp_v = base_sotp * dcf_v / base_dcf
            notes.append("sum of the parts scaled by the DCF's change (segments are valued on the same drivers)")
    weights = (ei.overrides or {}).get("blend_weights")
    vd = blend({"dcf": dcf_v, "comps": comps.get("comps"), "history": comps.get("history")}, ei.price.value, weights,
               sotp_v, dcf_value=dcf_v)
    y1 = None
    k0 = len(v.plan.skipped)
    if v.dcf and len(v.dcf.years) > k0 and v.dcf.shares:
        y1 = v.per_us_share(v.dcf.years[k0].nopat / v.dcf.shares)
    return Repriced(vd.fair_value, dcf_v, y1, vd.verdict, notes)


# --- priced in? ------------------------------------------------------------------------------------------------------
MARKET_ETF = "SPY"


def return_since(prices: list[dict], news_date: str) -> tuple[float, str, str] | None:
    """Return from the last close before the news date to the latest close: (return, from date, to date).
    None if there is no close before the news or none after it. Uses adjusted closes when present."""
    def px(r):  # plain closes: sources differ on adjustment, and over weeks dividends barely move the return
        return r["close"]
    before = [r for r in prices if r["date"] < news_date]
    after = [r for r in prices if r["date"] >= news_date]
    if not before or not after:
        return None
    a, b = before[-1], after[-1]
    return px(b) / px(a) - 1, a["date"], b["date"]


@dataclass
class PricedIn:
    stock_return: float | None
    market_return: float | None
    sector_return: float | None
    abnormal_vs_market: float | None
    abnormal_vs_sector: float | None
    window: str
    estimated_impact: float | None     # fair value change as a share of the price
    verdict: str                       # priced in / partly priced in / not priced in / moved the other way / ...
    note: str = ""


def priced_in(stock: list[dict], market: list[dict] | None, sector: list[dict] | None, news_date: str,
              estimated_impact: float | None) -> PricedIn:
    # One window for every series: end at the latest close they all have (a benchmark can lag by a day).
    have = [x for x in (stock, market, sector) if x]
    if have:
        end = min(x[-1]["date"] for x in have)
        stock, market, sector = ([r for r in x if r["date"] <= end] if x else x for x in (stock, market, sector))
    s = return_since(stock, news_date)
    if s is None:
        return PricedIn(None, None, None, None, None, "", estimated_impact, "too recent to judge",
                        "no trading close on both sides of the news date yet")
    m = return_since(market, news_date) if market else None
    sec = return_since(sector, news_date) if sector else None
    ab_m = s[0] - m[0] if m else None
    ab_s = s[0] - sec[0] if sec else None
    window = f"close {s[1]} to close {s[2]}"
    abn = ab_s if ab_s is not None else ab_m
    if abn is None:
        return PricedIn(s[0], None, None, None, None, window, estimated_impact, "no benchmark",
                        "market and sector prices unavailable")
    if estimated_impact is None:
        return PricedIn(s[0], m and m[0], sec and sec[0], ab_m, ab_s, window, None, "not comparable",
                        "impact is qualitative only")
    if abs(estimated_impact) < 0.005:
        verdict = "no material impact to price"
    elif abs(abn) < NOISE:
        verdict = "not priced in" if abs(estimated_impact) >= NOISE else "no material impact to price"
    elif abn * estimated_impact < 0 and abs(abn) >= 0.25 * abs(estimated_impact):
        verdict = "market moved the other way"
    elif abs(abn) >= 0.75 * abs(estimated_impact):
        verdict = "priced in"
    elif abs(abn) >= 0.25 * abs(estimated_impact):
        verdict = "partly priced in"
    else:
        verdict = "not priced in"
    basis = "sector ETF" if ab_s is not None else "S&P 500"
    return PricedIn(s[0], m and m[0], sec and sec[0], ab_m, ab_s, window, estimated_impact, verdict,
                    f"abnormal return vs the {basis} compared with the estimated fair value change as a share of "
                    f"the price")
