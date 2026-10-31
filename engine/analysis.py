"""Financial analysis (Section 6, item 4): growth, profitability, returns, quality of earnings,
working capital, balance sheet, capital allocation, management track record.

Pure functions over Historicals. Every metric is a calculated Value with its formula and inputs.
Commentary is generated from the computed numbers by rules (no AI), so every number in it is traceable.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from engine.model import Historicals
from engine.values import DAYS, MILLIONS, MULTIPLE, RATIO, Value, calc

DEFAULT_TAX_RATE = 0.21  # US federal statutory, used when the effective rate is not meaningful
TAX_RATE_BOUNDS = (0.0, 0.40)

SECTIONS = ("growth", "profitability", "returns", "quality", "working_capital", "balance_sheet",
            "capital_allocation", "track_record")


@dataclass
class Analysis:
    metrics: dict[str, dict[str, Value]] = field(default_factory=dict)  # metric -> period -> Value
    cagr: dict[str, Value] = field(default_factory=dict)
    debt_maturity: list[tuple[str, Value]] = field(default_factory=list)
    track_record: dict = field(default_factory=dict)
    commentary: dict[str, list[str]] = field(default_factory=dict)

    def m(self, name: str, period: str) -> float | None:
        v = self.metrics.get(name, {}).get(period)
        return None if v is None else v.value

    def put(self, name: str, period: str, v: Value | None) -> None:
        if v is not None and v.value is not None:
            self.metrics.setdefault(name, {})[period] = v


METRIC_SECTION = {
    "revenue_growth": "growth", "operating_income_growth": "growth", "fcf_growth": "growth",
    "gross_margin": "profitability", "ebitda_margin": "profitability", "operating_margin": "profitability",
    "fcf_margin": "profitability", "net_margin": "profitability",
    "effective_tax_rate": "returns", "nopat": "returns", "invested_capital": "returns", "roic": "returns",
    "roe": "returns", "asset_turnover": "returns", "equity_multiplier": "returns",
    "fcf_conversion": "quality", "accruals_ratio": "quality", "sbc_pct_revenue": "quality",
    "dso": "working_capital", "dio": "working_capital", "dpo": "working_capital", "ccc": "working_capital",
    "net_debt_to_ebitda": "balance_sheet", "interest_cover": "balance_sheet", "current_ratio": "balance_sheet",
    "quick_ratio": "balance_sheet",
    "capex_pct_cfo": "capital_allocation", "shareholder_returns": "capital_allocation",
    "share_count_change": "capital_allocation",
}


def _avg(h: Historicals, line: str, period: str, prev: str | None) -> Value | None:
    cur = h.get(line, period)
    if cur is None or cur.value is None:
        return None
    p = h.get(line, prev) if prev else None
    if p is None or p.value is None:
        return cur.with_note("period-end value used (no prior balance for an average)")
    return calc(lambda a, b: (a + b) / 2, f"average of {line} at {prev} and {period}", period, cur.unit,
                cur.currency, prior=p, current=cur)


def _cagr(h: Historicals, line: str, years: int) -> Value | None:
    fy = h.fy_labels
    if len(fy) <= years:
        return None
    start, end = h.get(line, fy[-1 - years]), h.get(line, fy[-1])
    if not start or not end or start.value is None or end.value is None or start.value <= 0 or end.value <= 0:
        return None
    return calc(lambda s, e: (e / s) ** (1 / years) - 1, f"({line} {fy[-1]} / {line} {fy[-1 - years]})^(1/{years}) - 1",
                f"{fy[-1 - years]}-{fy[-1]}", RATIO, None, start=start, end=end)


def _div(name: str, num: Value | None, den: Value | None, period: str, formula: str, unit: str = RATIO,
         scale: float = 1.0) -> Value | None:
    if num is None or den is None or num.value is None or den.value in (None, 0):
        return None
    return calc(lambda n, d: n / d * scale, formula, period, unit, None, n=num, d=den)


def analyse(h: Historicals, earnings_history: list[dict] | None = None,
            default_tax_rate: float = DEFAULT_TAX_RATE) -> Analysis:
    a = Analysis()
    labels = [p.label for p in h.periods]
    fy = h.fy_labels
    prev_of = {lab: (fy[i - 1] if i > 0 else None) for i, lab in enumerate(fy)}
    if h.ltm:
        prev_of[h.ltm.label] = fy[-1]  # average of last fiscal year-end and LTM balances (closest available)
    g = h.get

    for p in labels:
        prev = prev_of.get(p)
        # --- growth (fiscal years only) ---------------------------------------------------
        if p in fy and prev:
            for metric, line in (("revenue_growth", "revenue"), ("operating_income_growth", "operating_income"),
                                 ("fcf_growth", "fcf")):
                cur, pv = g(line, p), g(line, prev)
                if cur and pv and cur.value is not None and pv.value not in (None, 0) and pv.value > 0:
                    a.put(metric, p, calc(lambda c, q: c / q - 1, f"{line} {p} / {line} {prev} - 1", p, RATIO, None,
                                          current=cur, prior=pv))
        # --- profitability -------------------------------------------------------------------
        rev = g("revenue", p)
        for metric, line in (("gross_margin", "gross_profit"), ("ebitda_margin", "ebitda"),
                             ("operating_margin", "operating_income"), ("fcf_margin", "fcf"),
                             ("net_margin", "net_income_attributable")):
            v = _div(metric, g(line, p), rev, p, f"{line} / revenue")
            if v:
                a.put(metric, p, v)
        # --- tax, NOPAT, invested capital, ROIC -----------------------------------------------
        tax, pre = g("income_tax", p), g("pretax_income", p)
        etr = _div("etr", tax, pre, p, "income_tax / pretax_income")
        if etr is None or not (TAX_RATE_BOUNDS[0] <= etr.value <= TAX_RATE_BOUNDS[1]):
            reason = "not reported" if etr is None else f"effective rate {etr.value:.1%} outside 0-40%"
            etr = Value(default_tax_rate, None, RATIO, p, "assumption", note=f"statutory rate used: {reason}")
        a.put("effective_tax_rate", p, etr)
        oi = g("operating_income", p)
        if oi and oi.value is not None:
            nopat = calc(lambda o, t: o * (1 - t), "operating_income x (1 - tax rate)", p, MILLIONS, h.currency,
                         o=oi, t=etr)
            a.put("nopat", p, nopat)
        eq, debt, cash = g("total_equity", p), g("debt_for_valuation", p), g("cash_and_investments", p)
        if eq and debt and cash and None not in (eq.value, debt.value, cash.value):
            inv = h.non_operating_investments(p)
            if inv is not None:  # valued in the equity bridge, so not capital the operations earn on
                ic_v = calc(lambda e, d, c, i: e + d - c - i,
                            "total_equity + debt_for_valuation - cash_and_investments - long_term_investments",
                            p, MILLIONS, h.currency, e=eq, d=debt, c=cash, i=inv)
            else:
                ic_v = calc(lambda e, d, c: e + d - c, "total_equity + debt_for_valuation - cash_and_investments",
                            p, MILLIONS, h.currency, e=eq, d=debt, c=cash)
            a.put("invested_capital", p, ic_v)
    for p in labels:
        prev = prev_of.get(p)
        ic_now, ic_prev = a.metrics.get("invested_capital", {}).get(p), a.metrics.get("invested_capital", {}).get(prev)
        nopat = a.metrics.get("nopat", {}).get(p)
        if nopat and ic_now:
            ic = ic_now if not ic_prev else calc(lambda x, y: (x + y) / 2, "average invested capital", p, MILLIONS,
                                                 h.currency, prior=ic_prev, current=ic_now)
            if ic.value and ic.value > 0:
                a.put("roic", p, calc(lambda n, i: n / i, "NOPAT / average invested capital", p, RATIO, None,
                                      nopat=nopat, invested_capital=ic))
        avg_pe, avg_ta = _avg(h, "parent_equity", p, prev), _avg(h, "total_assets", p, prev)
        ni, rev = g("net_income_attributable", p), g("revenue", p)
        if avg_pe and avg_pe.value and avg_pe.value > 0:
            v = _div("roe", ni, avg_pe, p, "net_income_attributable / average shareholders' equity")
            if v:
                a.put("roe", p, v)
            v = _div("em", avg_ta, avg_pe, p, "average total assets / average shareholders' equity", MULTIPLE)
            if v:
                a.put("equity_multiplier", p, v)
        v = _div("at", rev, avg_ta, p, "revenue / average total assets", MULTIPLE)
        if v:
            a.put("asset_turnover", p, v)
        # --- quality of earnings -------------------------------------------------------------
        v = _div("conv", g("fcf", p), ni, p, "fcf / net_income_attributable", MULTIPLE)
        if v and ni.value and ni.value > 0:
            a.put("fcf_conversion", p, v)
        cfo = g("cfo", p)
        if ni and cfo and avg_ta and None not in (ni.value, cfo.value) and avg_ta.value:
            a.put("accruals_ratio", p, calc(lambda n, c, t: (n - c) / t, "(net income - CFO) / average total assets",
                                            p, RATIO, None, n=ni, c=cfo, t=avg_ta))
        v = _div("sbc", g("sbc", p), rev, p, "sbc / revenue")
        if v:
            a.put("sbc_pct_revenue", p, v)
        # --- working capital (period-end balances) -------------------------------------------------
        cogs = g("cost_of_revenue", p)
        for metric, line, den, label in (("dso", "receivables", rev, "revenue"),
                                         ("dio", "inventory", cogs, "cost_of_revenue"),
                                         ("dpo", "accounts_payable", cogs, "cost_of_revenue")):
            v = _div(metric, g(line, p), den, p, f"{line} / {label} x 365", DAYS, 365.0)
            if v:
                a.put(metric, p, v)
        dso, dio, dpo = (a.metrics.get(k, {}).get(p) for k in ("dso", "dio", "dpo"))
        if dso and dpo:
            dio_v = dio or Value(0.0, None, DAYS, p, "assumed zero", note="no inventory reported")
            a.put("ccc", p, calc(lambda s, i, q: s + i - q, "DSO + DIO - DPO", p, DAYS, None, s=dso, i=dio_v, q=dpo))
        # --- balance sheet ------------------------------------------------------------------------
        nd, ebitda = g("net_debt", p), g("ebitda", p)
        if nd and ebitda and ebitda.value and ebitda.value > 0:
            a.put("net_debt_to_ebitda", p, _div("nd", nd, ebitda, p, "net_debt / ebitda", MULTIPLE))
        ie = g("interest_expense", p)
        if oi := g("operating_income", p):
            v = _div("ic", oi, ie, p, "operating_income / interest_expense", MULTIPLE)
            if v and ie.value and ie.value > 0:
                a.put("interest_cover", p, v)
        cl = g("current_liabilities", p)
        v = _div("cr", g("current_assets", p), cl, p, "current_assets / current_liabilities", MULTIPLE)
        if v:
            a.put("current_ratio", p, v)
        quick = [g(x, p) for x in ("cash", "short_term_investments", "receivables")]
        if quick[0] and quick[0].value is not None and cl and cl.value:
            parts = {k: (q if q and q.value is not None else Value(0.0, h.currency, MILLIONS, p, "assumed zero"))
                     for k, q in zip(("cash", "sti", "rec"), quick)}
            a.put("quick_ratio", p, calc(lambda cash, sti, rec, l_: (cash + sti + rec) / l_,
                                         "(cash + short-term investments + receivables) / current_liabilities",
                                         p, MULTIPLE, None, **parts, l_=cl))
        # --- capital allocation ------------------------------------------------------------------
        v = _div("capex_cfo", g("capex", p), cfo, p, "capex / cfo")
        if v and cfo.value and cfo.value > 0:
            a.put("capex_pct_cfo", p, v)
        bb, dv = g("buybacks", p), g("dividends_paid", p)
        if (bb and bb.value is not None) or (dv and dv.value is not None):
            zero = lambda: Value(0.0, h.currency, MILLIONS, p, "assumed zero", note="not reported")  # noqa: E731
            a.put("shareholder_returns", p, calc(lambda b, d: b + d, "buybacks + dividends_paid", p, MILLIONS,
                                                 h.currency, b=bb if bb and bb.value is not None else zero(),
                                                 d=dv if dv and dv.value is not None else zero()))
        if p in fy and prev:
            s1, s0 = g("shares_diluted_weighted", p), g("shares_diluted_weighted", prev)
            if s1 and s0 and s1.value and s0.value:
                a.put("share_count_change", p, calc(lambda x, y: x / y - 1, "diluted shares / prior diluted shares - 1",
                                                    p, RATIO, None, current=s1, prior=s0))

    for line in ("revenue", "operating_income", "fcf"):
        for years in (3, 5):
            v = _cagr(h, line, years)
            if v:
                a.cagr[f"{line}_cagr_{years}y"] = v

    if fy:
        last = fy[-1]
        for i, name in enumerate(("debt_due_y1", "debt_due_y2", "debt_due_y3", "debt_due_y4", "debt_due_y5",
                                  "debt_due_after_y5")):
            v = g(name, last)
            if v and v.value is not None:
                a.debt_maturity.append((f"Year {i + 1}" if i < 5 else "After year 5", v))

    if earnings_history:
        rows = [r for r in earnings_history if r.get("eps_actual") is not None and r.get("eps_estimate") is not None]
        beats = sum(1 for r in rows if r["eps_actual"] > r["eps_estimate"])
        a.track_record = {"quarters": len(rows), "eps_beats": beats,
                          "beat_rate": beats / len(rows) if rows else None,
                          "average_surprise": (sum((r["eps_actual"] - r["eps_estimate"]) / abs(r["eps_estimate"])
                                                   for r in rows if r["eps_estimate"]) / len(rows)) if rows else None,
                          "rows": rows[:12]}
    a.commentary = commentary(h, a)
    return a


# --- rule-based commentary --------------------------------------------------------------------------
def _pct(x: float | None) -> str:
    return "n/a" if x is None else f"{x * 100:.1f}%"


def _x(x: float | None) -> str:
    return "n/a" if x is None else f"{x:.1f}x"


def commentary(h: Historicals, a: Analysis) -> dict[str, list[str]]:
    fy = h.fy_labels
    if not fy:
        return {}
    last = fy[-1]
    prev = fy[-2] if len(fy) > 1 else None
    out: dict[str, list[str]] = {s: [] for s in SECTIONS}
    rg = a.m("revenue_growth", last)
    if rg is not None:
        c3 = a.cagr.get("revenue_cagr_3y")
        out["growth"].append(f"Revenue grew {_pct(rg)} in {last}"
                             + (f", against a 3-year CAGR of {_pct(c3.value)}." if c3 else "."))
    og = a.m("operating_income_growth", last)
    if og is not None:
        out["growth"].append(f"Operating income {'rose' if og >= 0 else 'fell'} {_pct(abs(og))}.")
    om, om_prev = a.m("operating_margin", last), a.m("operating_margin", prev) if prev else None
    if om is not None:
        trend = "" if om_prev is None else (", up from " if om > om_prev else ", down from ") + _pct(om_prev)
        out["profitability"].append(f"Operating margin was {_pct(om)} in {last}{trend}.")
    fm = a.m("fcf_margin", last)
    if fm is not None:
        out["profitability"].append(f"Free cash flow margin was {_pct(fm)}.")
    roic = a.m("roic", last)
    if roic is not None:
        out["returns"].append(f"ROIC was {_pct(roic)} in {last} (compared with WACC in the valuation section).")
    roe = a.m("roe", last)
    if roe is not None:
        out["returns"].append(f"ROE was {_pct(roe)}: net margin {_pct(a.m('net_margin', last))} x asset turnover "
                              f"{_x(a.m('asset_turnover', last))} x equity multiplier {_x(a.m('equity_multiplier', last))}.")
    conv = a.m("fcf_conversion", last)
    if conv is not None:
        out["quality"].append(f"Free cash flow was {_x(conv)} net income"
                              + (" — weak cash conversion." if conv < 0.8 else "."))
    sbc = a.m("sbc_pct_revenue", last)
    if sbc is not None:
        out["quality"].append(f"Share-based compensation was {_pct(sbc)} of revenue; the DCF treats it as a cash cost.")
    gap = h.v("non_operating_and_tax_gap", last)
    if gap is not None and h.v("operating_income", last) is not None and gap > 0.5 * abs(h.v("operating_income", last)):
        out["quality"].append(f"Net income exceeded operating income by {gap:,.0f}m in {last}, pointing to "
                              f"non-operating or tax items; forecasts are built on operating income.")
    ccc = a.m("ccc", last)
    if ccc is not None:
        out["working_capital"].append(f"Cash conversion cycle of {ccc:.0f} days (DSO {a.m('dso', last):.0f}, "
                                      f"DPO {a.m('dpo', last):.0f}).")
    nd = h.v("net_debt", last)
    if nd is not None:
        lev = a.m("net_debt_to_ebitda", last)
        out["balance_sheet"].append(
            (f"Net cash of {-nd:,.0f}m" if nd < 0 else f"Net debt of {nd:,.0f}m")
            + (f" ({_x(lev)} EBITDA)." if lev is not None and nd > 0 else " (including leases)."))
    cov = a.m("interest_cover", last)
    if cov is not None:
        out["balance_sheet"].append(f"Operating income covered interest {_x(cov)}.")
    sr = h.v("buybacks", last)
    if sr:
        out["capital_allocation"].append(f"Bought back {sr:,.0f}m of shares in {last}.")
    sc = a.m("share_count_change", last)
    if sc is not None:
        out["capital_allocation"].append(f"Diluted share count {'rose' if sc > 0 else 'fell'} {_pct(abs(sc))}.")
    tr = a.track_record
    if tr.get("quarters"):
        out["track_record"].append(f"Beat EPS consensus in {tr['eps_beats']} of the last {tr['quarters']} quarters.")
    return out
