"""The report's Monte Carlo (pure): the DCF re-run on random assumptions, with growth and margin drawn at the
company's own measured correlation. One place computes it, so the app, the exports and the rating all use the same
figures (the rating may not be a Buy when almost no runs land above the price)."""
from __future__ import annotations

from functools import lru_cache

from engine.classify import DECLINING
from engine.insights import (MIN_CORR_YEARS, growth_margin_correlation, monte_carlo,
                             pooled_growth_margin_correlation)


@lru_cache(maxsize=32)
def mc_cached(inp, price: float, cap: float | None, rho: float = 0.0):
    return monte_carlo(inp, price, max_terminal_growth=cap, growth_margin_corr=rho)


def history_pairs(rep) -> list[tuple[float, float]]:
    """(revenue growth, change in operating margin) for each reported fiscal year after the first."""
    h, a = getattr(rep.company, "historicals_usd", None), getattr(rep.company, "analysis", None)
    if h is None or a is None:
        return []
    out = []
    for prev, cur in zip(h.fy_labels, h.fy_labels[1:]):
        g, m0, m1 = a.m("revenue_growth", cur), a.m("operating_margin", prev), a.m("operating_margin", cur)
        if None not in (g, m0, m1):
            out.append((g, m1 - m0))
    return out


def mc_for(rep) -> tuple[dict | None, dict | None, dict | None]:
    """The report's Monte Carlo with growth and margin drawn at the company's own measured correlation, that
    correlation (None if under six years of history: then the draws are independent), and the independent run for
    comparison. Prices are per ordinary share."""
    m = rep.model
    v = m.valuation
    cap = 0.0 if v.classification.stage == DECLINING else m.inputs.risk_free.value
    price = m.verdict.price / v.per_us_share_factor
    own = history_pairs(rep)
    corr = growth_margin_correlation(own)
    if corr:
        corr["basis"] = f"the company's last {corr['n']} years"
    else:  # too short a history of its own: pool it with the peers'
        series = {rep.ticker: own, **{p.ticker: list(getattr(p, "growth_margin_pairs", ()))
                                      for p in (getattr(rep, "peers_pool", None)
                                                or (rep.model.comps.peers if rep.model.comps else []))}}
        corr = pooled_growth_margin_correlation(series)
        if corr:
            corr["basis"] = (f"{corr['n']} company-years pooled across {', '.join(corr['firms'])} (each firm against "
                             f"its own averages), because the company has under {MIN_CORR_YEARS} years of its own")
    rho = corr["rho"] if corr else 0.0
    ind = mc_cached(v.dcf_inputs, price, cap, 0.0)
    return (mc_cached(v.dcf_inputs, price, cap, rho) if rho else ind), corr, ind
