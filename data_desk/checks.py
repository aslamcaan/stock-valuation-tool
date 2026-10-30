"""Data checks (pure). Thresholds come from CLAUDE.md ACCURACY RULES.

Hard stops: balance sheet off by >0.5% in a period used for valuation; computed market cap >3% from
the provider's. Red flags (1% tolerance): statement lines not summing; cash flow not tying to the change
in cash. Amber: EDGAR vs FMP >2%; stale filings (>120 days); plus corporate warning flags.
"""
from __future__ import annotations

from datetime import date

from engine.model import Historicals
from engine.comps import earnings_distorted
from engine.flags import AMBER, HARD_STOP, INFO, RED, Flag, rel_diff

BS_TOLERANCE = 0.005
MCAP_TOLERANCE = 0.03
SUM_TOLERANCE = 0.01
CROSS_SOURCE_TOLERANCE = 0.02
STALE_DAYS = 120
KPI_GAP_POINTS = 0.05


def checked_periods(h: Historicals, years: int = 5) -> list[str]:
    """Statement checks cover the last `years` fiscal years plus LTM (older years only appear in an expander)."""
    return h.fy_labels[-years:] + ([h.ltm.label] if h.ltm else [])


def _fmt(x: float | None) -> str:
    return "n/a" if x is None else f"{x:,.1f}"


def balance_sheet(h: Historicals, valuation_periods: list[str]) -> list[Flag]:
    """Assets = liabilities + temporary equity + total equity. Hard stop only for valuation periods."""
    flags = []
    for p in checked_periods(h):
        a, l_, e = h.v("total_assets", p), h.v("total_liabilities", p), h.v("total_equity", p)
        t = h.v("temporary_equity", p) or 0.0
        if None in (a, l_, e):
            if p in valuation_periods:
                flags.append(Flag(AMBER, "bs_incomplete", "Balance sheet check not possible",
                                  f"{p}: total assets, liabilities or equity not reported, so the balance sheet "
                                  f"could not be checked.", p, {"assets": a, "liabilities": l_, "equity": e}))
            continue
        diff = rel_diff(a, l_ + t + e)
        if diff > BS_TOLERANCE:
            level = HARD_STOP if p in valuation_periods else RED
            flags.append(Flag(level, "bs_not_balancing", "Balance sheet does not balance",
                              f"{p}: total assets {_fmt(a)} vs liabilities {_fmt(l_)} + redeemable equity {_fmt(t)} "
                              f"+ equity {_fmt(e)} = {_fmt(l_ + t + e)} (off by {diff:.2%}, limit 0.5%).",
                              p, {"assets": a, "liabilities": l_, "temporary_equity": t, "equity": e, "diff": diff}))
    return flags


def statement_sums(h: Historicals) -> list[Flag]:
    flags = []
    for p in checked_periods(h):
        rev, cogs, gp = h.get("revenue", p), h.get("cost_of_revenue", p), h.get("gross_profit", p)
        if rev and cogs and gp and gp.source != "calculated" and None not in (rev.value, cogs.value, gp.value):
            d = rel_diff(rev.value - cogs.value, gp.value)
            if d > SUM_TOLERANCE:
                flags.append(Flag(RED, "is_gross_profit_sum", "Income statement lines do not sum",
                                  f"{p}: revenue {_fmt(rev.value)} - cost of revenue {_fmt(cogs.value)} = "
                                  f"{_fmt(rev.value - cogs.value)}, but reported gross profit is {_fmt(gp.value)} "
                                  f"({d:.1%} gap).", p, {"revenue": rev.value, "cost_of_revenue": cogs.value,
                                                         "gross_profit": gp.value}))
        ca, ta = h.v("current_assets", p), h.v("total_assets", p)
        if ca is not None and ta is not None and ca > ta * (1 + SUM_TOLERANCE):
            flags.append(Flag(RED, "bs_current_exceeds_total", "Balance sheet lines do not sum",
                              f"{p}: current assets {_fmt(ca)} exceed total assets {_fmt(ta)}.", p,
                              {"current_assets": ca, "total_assets": ta}))
        le, a = h.v("liabilities_and_equity", p), h.v("total_assets", p)
        if le is not None and a is not None and rel_diff(le, a) > SUM_TOLERANCE:
            flags.append(Flag(RED, "bs_total_mismatch", "Balance sheet totals differ",
                              f"{p}: total assets {_fmt(a)} vs total liabilities and equity {_fmt(le)}.", p,
                              {"total_assets": a, "liabilities_and_equity": le}))
    return flags


def cash_flow_tie(h: Historicals) -> list[Flag]:
    """CFO + CFI + CFF (+ FX) = change in cash, within 1% of the largest cash flow section."""
    flags = []
    for p in checked_periods(h):
        cfo, cfi, cff = h.v("cfo", p), h.v("cfi", p), h.v("cff", p)
        if None in (cfo, cfi, cff):
            continue
        fx = h.v("fx_effect_on_cash", p) or 0.0
        total, before_fx = h.v("change_in_cash", p), h.v("change_in_cash_before_fx", p)
        if total is not None:
            computed, reported, what = cfo + cfi + cff + fx, total, "including FX"
        elif before_fx is not None:
            computed, reported, what = cfo + cfi + cff, before_fx, "before FX"
        else:
            continue
        scale = max(abs(cfo), abs(cfi), abs(cff), 1.0)
        if abs(computed - reported) / scale > SUM_TOLERANCE:
            flags.append(Flag(RED, "cf_not_tying", "Cash flow does not tie to the change in cash",
                              f"{p}: operating {_fmt(cfo)} + investing {_fmt(cfi)} + financing {_fmt(cff)}"
                              f"{f' + FX {_fmt(fx)}' if what == 'including FX' else ''} = {_fmt(computed)}, "
                              f"but the reported change in cash ({what}) is {_fmt(reported)}.", p,
                              {"cfo": cfo, "cfi": cfi, "cff": cff, "fx": fx, "reported_change": reported}))
    return flags


def market_cap(computed: float | None, provider: float | None, provider_name: str, detail: str,
               point_in_time_shares: bool = True) -> list[Flag]:
    """Hard stop at >3%, but only when the share count is a point-in-time count. A weighted-average
    fallback cannot support a hard stop, so a gap is then amber."""
    if computed is None or provider is None:
        return [Flag(AMBER, "mcap_unchecked", "Market cap could not be cross-checked",
                     f"Market cap check skipped: {detail}", None, {"computed": computed, "provider": provider})]
    d = rel_diff(computed, provider)
    if d > MCAP_TOLERANCE and not provider_name.upper().startswith("FMP"):
        # the brief's hard stop is against FMP; a secondary provider's market cap often uses a stale share count
        return [Flag(AMBER, "mcap_mismatch_secondary", "Market cap differs from a secondary provider",
                     f"Computed market cap {_fmt(computed)}m vs {provider_name} {_fmt(provider)}m ({d:.1%} apart). "
                     f"FMP was unavailable, and {provider_name}'s figure can lag the share count, so this is not a "
                     f"hard stop. {detail}", None, {"computed": computed, "provider": provider, "diff": d})]
    if d > MCAP_TOLERANCE and not point_in_time_shares:
        return [Flag(AMBER, "mcap_mismatch_approx", "Market cap check is approximate",
                     f"Computed market cap {_fmt(computed)}m vs {provider_name} {_fmt(provider)}m ({d:.1%} apart). "
                     f"The share count is not a current point-in-time figure, so this cannot be a hard stop. {detail}", None,
                     {"computed": computed, "provider": provider, "diff": d})]
    if d > MCAP_TOLERANCE:
        return [Flag(HARD_STOP, "mcap_mismatch", "Market cap does not match the data provider",
                     f"Computed market cap {_fmt(computed)}m vs {provider_name} {_fmt(provider)}m "
                     f"({d:.1%} apart, limit 3%). {detail}", None,
                     {"computed": computed, "provider": provider, "diff": d})]
    return []


def cross_source(edgar: dict[str, float | None], other: dict[str, float | None], source: str,
                 period: str) -> list[Flag]:
    flags = []
    for k, ev in edgar.items():
        ov = other.get(k)
        if ev is None or ov is None:
            continue
        d = rel_diff(ev, ov)
        if d > CROSS_SOURCE_TOLERANCE:
            flags.append(Flag(AMBER, f"xsource_{k}", f"EDGAR and {source} disagree on {k.replace('_', ' ')}",
                              f"{period}: EDGAR {_fmt(ev)} vs {source} {_fmt(ov)} ({d:.1%} apart, limit 2%).",
                              period, {"edgar": ev, source: ov, "diff": d}))
    return flags


def filing_age(filed: str | None, form: str | None, today: date) -> list[Flag]:
    if not filed:
        return []
    age = (today - date.fromisoformat(filed)).days
    if age > STALE_DAYS:
        return [Flag(AMBER, "stale_filing", "Latest financial filing is old",
                     f"The latest financial statements ({form} filed {filed}) are {age} days old (limit 120). "
                     f"Recent results may not be reflected.", None, {"age_days": age})]
    return []


def net_income_vs_operating(h: Historicals) -> list[Flag]:
    """Net income far above operating income: gap > 50% of |operating income| and > 5% of revenue."""
    flags = []
    for p in checked_periods(h):
        ni, oi, rev = h.v("net_income_attributable", p), h.v("operating_income", p), h.v("revenue", p)
        if None in (ni, oi, rev) or rev <= 0:
            continue
        gap = ni - oi
        if earnings_distorted(ni, oi, rev):
            flags.append(Flag(AMBER, "ni_far_above_oi", "Net income far above operating income",
                              f"{p}: net income {_fmt(ni)} vs operating income {_fmt(oi)} (gap {_fmt(gap)}, "
                              f"{gap / rev:.1%} of revenue). Likely one-off tax or investment gains; forecasts use "
                              f"operating income.", p, {"net_income": ni, "operating_income": oi, "revenue": rev}))
    return flags


def negative_fcf(h: Historicals) -> list[Flag]:
    p = h.ltm.label if h.ltm and h.v("fcf", h.ltm.label) is not None else (h.fy_labels[-1] if h.fy_labels else None)
    f = h.v("fcf", p) if p else None
    if f is not None and f < 0:
        return [Flag(AMBER, "negative_fcf", "Negative free cash flow",
                     f"{p}: free cash flow (CFO - capex) is {_fmt(f)}.", p, {"fcf": f})]
    return []


def kpi_divergence(h: Historicals, kpi_name: str, kpi: dict[str, float]) -> list[Flag]:
    """Revenue growth vs a reported volume KPI (e.g. gross bookings) diverging by more than 5 points."""
    flags = []
    labels = [p for p in h.fy_labels if p in kpi]
    for prev, cur in zip(labels, labels[1:]):
        r0, r1 = h.v("revenue", prev), h.v("revenue", cur)
        if not (r0 and r1):
            continue
        rg, kg = r1 / r0 - 1, kpi[cur] / kpi[prev] - 1
        if abs(rg - kg) > KPI_GAP_POINTS:
            flags.append(Flag(AMBER, "kpi_divergence", f"Revenue growth diverges from {kpi_name}",
                              f"{cur}: revenue grew {rg:.1%} but {kpi_name} grew {kg:.1%} "
                              f"({abs(rg - kg) * 100:.1f} points apart, limit 5).", cur,
                              {"revenue_growth": rg, f"{kpi_name}_growth": kg}))
    return flags


KEY_LINES = {"revenue": "revenue", "operating_income": "operating income", "cash": "cash",
             "total_debt": "total debt", "shares_diluted_weighted": "diluted share count", "cfo": "operating cash flow"}


def missing_key_lines(h: Historicals, valuation_periods: list[str]) -> list[Flag]:
    """Say so when a line the valuation depends on is missing (CLAUDE.md: never hide missing data)."""
    flags = []
    for p in valuation_periods:
        absent = [label for line, label in KEY_LINES.items() if h.v(line, p) is None]
        if absent:
            flags.append(Flag(AMBER, "missing_key_line", "Key figures missing",
                              f"{p}: {', '.join(absent)} not found in the filing data. Results that depend on "
                              f"them are incomplete.", p, {"missing": absent}))
    return flags


def ambiguous_debt(h: Historicals, valuation_periods: list[str], marker: str) -> list[Flag]:
    flags = []
    for p in valuation_periods:
        v = h.get("total_debt", p)
        if v is not None and v.note and marker in v.note:
            flags.append(Flag(AMBER, "debt_tags_ambiguous", "Debt tags overlap", f"{p}: {v.note}.", p,
                              {"total_debt": v.value}))
    return flags


def convertible_debt(evidence: list[str]) -> list[Flag]:
    if not evidence:
        return []
    return [Flag(AMBER, "convertible_debt", "Convertible debt outstanding",
                 "Convertible debt found in recent filings; dilution on conversion is not in the share count. "
                 f"Evidence: {evidence[0]}", None, {})]


def currency_mismatch(reporting: str, trading: str = "USD") -> list[Flag]:
    if reporting == trading:
        return []
    return [Flag(INFO, "currency_mismatch", "Reporting currency differs from trading currency",
                 f"Financial statements are in {reporting}; the shares trade in {trading}. Figures are converted "
                 f"with FRED rates (period-average for income statement and cash flow, period-end for balance sheet).",
                 None, {})]


def multiple_share_classes(n_classes: int, detail: str) -> list[Flag]:
    if n_classes <= 1:
        return []
    return [Flag(AMBER, "multiple_share_classes", "Multiple share classes",
                 f"{n_classes} share classes found ({detail}). Market cap and per-share values use all classes "
                 f"combined; check voting control and any price differences between classes.", None,
                 {"classes": n_classes})]
