"""What the price needs, and what is on offer from here (pure, all arithmetic in Python).

`expectations(rep)`: the revenue CAGR and the terminal operating margin the share price needs (each solved on its own
with everything else at the base case), against the company's best year on record and its mid-cycle margin.
`risk_reward(rep)`: percentage to the bear, base and bull DCF from the price, the share of Monte Carlo runs above the
price, and the probability-weighted expected return at the scenario weights (25/50/25).
Both return None for a company with no DCF (the bank, insurer and REIT toolkits), and both state what is missing
rather than filling it in."""
from __future__ import annotations

from engine.classify import margins
from engine.insights import implied_assumptions
from engine.report_mc import mc_for
from engine.scenarios import DEFAULT_SCENARIOS


def _best_growth(rep) -> tuple[float, str] | None:
    a, h = getattr(rep.company, "analysis", None), getattr(rep.company, "historicals_usd", None)
    if a is None or h is None:
        return None
    xs = [(a.m("revenue_growth", p), p) for p in h.fy_labels[-10:]]
    xs = [(g, p) for g, p in xs if g is not None]
    return max(xs) if xs else None


def expectations(rep) -> dict | None:
    m = getattr(rep, "model", None)
    v = getattr(m, "valuation", None)
    if v is None or v.dcf_inputs is None or getattr(m, "financial", None) is not None:
        return None
    price_us = m.verdict.price
    factor = v.per_us_share_factor or 1.0
    imp = implied_assumptions(v.dcf_inputs, price_us / factor)
    best = _best_growth(rep)
    cyc = v.cycle if v.cycle.get("available") else {}
    mids = [mm for _, mm in margins(rep.company.historicals_usd)] if getattr(rep.company, "historicals_usd", None) else []
    mid_margin = cyc.get("median_margin") if cyc else (sorted(mids)[len(mids) // 2] if mids else None)
    best_margin = cyc.get("max_margin") if cyc else (max(mids) if mids else None)
    years = len(v.dcf_inputs.years)
    out = {"ticker": rep.ticker, "price": price_us, "years": years, "implied_cagr": None, "implied_terminal_margin": None,
           "base_cagr": None, "base_terminal_margin": None, "best_year_growth": best[0] if best else None,
           "best_year": best[1] if best else None, "mid_cycle_margin": mid_margin, "best_year_margin": best_margin,
           "current_margin": cyc.get("current_margin") if cyc else None, "lines": []}
    if imp:
        out.update(implied_cagr=imp["implied_cagr"], implied_terminal_margin=imp["implied_terminal_margin"],
                   base_cagr=imp["base_cagr"], base_terminal_margin=imp["base_terminal_margin"])
    t = rep.ticker
    if out["implied_cagr"] is not None:
        line = f"{t} at ${price_us:,.2f} needs {out['implied_cagr']:.1%} revenue growth a year for {years} years"
        line += (f". Best year on record is {out['best_year_growth']:.1%} ({out['best_year']})."
                 if best else ". The best year on record is not available.")
        out["lines"].append(line)
    if out["implied_terminal_margin"] is not None:
        line = f"Or, on its own, a terminal operating margin of {out['implied_terminal_margin']:.1%}"
        refs = []
        if mid_margin is not None:
            refs.append(f"median {mid_margin:.1%}")
        if best_margin is not None:
            refs.append(f"best year {best_margin:.1%}")
        out["lines"].append(line + (f" (company's own margins: {', '.join(refs)})." if refs else "."))
    if not out["lines"]:
        out["lines"].append(f"No growth rate or margin within the search range reaches ${price_us:,.2f} on this model; "
                            "the price needs a different business from the one in the base case.")
    out["base_line"] = (f"Our base case: {out['base_cagr']:.1%} a year and a terminal margin of "
                        f"{out['base_terminal_margin']:.1%}." if imp else "")
    out["stretch"] = None if not best or out["implied_cagr"] is None else out["implied_cagr"] > best[0]
    return out


def risk_reward(rep) -> dict | None:
    m = getattr(rep, "model", None)
    v = getattr(m, "valuation", None)
    if v is None or v.dcf_inputs is None or getattr(m, "financial", None) is not None:
        return None
    price = m.verdict.price
    fig = v.dcf_figures or {}
    pts = {k: fig.get(k) for k in ("bear", "base", "bull")}
    pct = {k: (None if x is None or not price else x / price - 1) for k, x in pts.items()}
    weights = {s.name.lower(): s.probability for s in DEFAULT_SCENARIOS}
    expected = None
    if all(pts.get(k) is not None for k in weights):
        expected = sum(w * pts[k] for k, w in weights.items()) / price - 1
    mc = None
    try:
        mc_res, _, _ = mc_for(rep)
        mc = mc_res["prob_above_price"] if mc_res else None
    except Exception:  # noqa: BLE001  (no Monte Carlo is a missing figure, not a failed report)
        mc = None
    fit_failed = bool(getattr(v, "model_fit_failed", False))

    def p(x):
        return "n/a" if x is None else f"{x:+.0%}"
    line = (f"To bear {p(pct['bear'])} · base {p(pct['base'])} · bull {p(pct['bull'])} · "
            f"{'n/a' if mc is None else f'{mc:.0%}'} of Monte Carlo runs above the price · expected return "
            f"{p(expected)} at {'/'.join(f'{w:.0%}' for w in weights.values()).replace('%', '')} weights")
    if fit_failed:
        line += " (the DCF failed its fit check: treat these as unreliable)"
    return {"price": price, "values": pts, "pct": pct, "prob_above_price": mc, "expected_return": expected,
            "weights": weights, "fit_failed": fit_failed, "line": line}
