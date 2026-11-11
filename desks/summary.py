"""Compact, rounded summary of the computed results that the AI desks read. The same numbers form the number
guard's allowed set, so the AI can only quote what is here (or in the filing quotes it is given)."""
from __future__ import annotations


def _r(x, nd=4):
    return None if x is None else round(float(x), nd)


RULE_THRESHOLDS = {"terminal_value_share_of_ev_max": 0.80, "whole_enterprise_value": 1.0, "wacc_min": 0.06,
                   "wacc_max": 0.15, "terminal_growth_max": 0.04, "market_cap_tolerance": 0.03,
                   "balance_sheet_tolerance": 0.005, "edgar_vs_fmp_tolerance": 0.02, "statement_sum_tolerance": 0.01,
                   "kpi_divergence_points": 5, "stale_filing_days": 120, "cyclical_peak_percentile": 90,
                   "beneish_m_threshold": -1.78}

def components_of(vd) -> dict:
    """The blend's components by name. When a sum of the parts replaced the DCF it is named as such, so no desk can
    mistake it for the DCF (which is dcf.figures)."""
    sotp = bool(getattr(vd, "dcf_is_sotp", False))
    return {("sum_of_the_parts" if k == "dcf" and sotp else k): _r(x, 2) for k, x in vd.components.items()}


def calendar_of(report) -> dict:
    """The price's timestamp and the next results date, so the MD can date the earnings catalyst. The date also appears
    as separate numbers (year, month, day), which the number guard can then match when the text writes it out."""
    m = getattr(getattr(report, "company", None), "market", None)
    out: dict = {}
    price = getattr(m, "price", None)
    if price is not None:
        out["price_as_of"] = str(price.period)
    ne = getattr(m, "next_earnings", None)
    if ne and ne.get("date"):
        y, mo, d = (int(x) for x in ne["date"][:10].split("-"))
        out["next_earnings"] = {"date": ne["date"][:10], "year": y, "month": mo, "day": d,
                                "eps_estimate": _r(ne.get("eps_estimate"), 2), "source": "earnings calendar"}
    else:
        out["next_earnings"] = None
    return out


def financial_summary(report, research: dict | None = None) -> dict:
    """Banks, insurers, REITs: the toolkit's metrics (computed and reported) and valuation methods."""
    from engine.financials import method_label
    from ui.financial import FS_LINES
    cd, fv, vd = report.company, report.financial, report.verdict
    h = cd.historicals_usd
    periods = h.fy_labels[-4:]
    d = fv.detail
    methods = {}
    for k, val in fv.methods.items():
        x = {"label": method_label(k, fv.toolkit), "value_per_share": _r(val.value, 2)}
        if k == "justified":
            x["justified_multiple"] = _r(d[k]["multiple"], 3)
        if k in ("residual_income", "ddm"):
            x.update(pv_explicit=_r(d[k]["pv_explicit"], 2), pv_terminal=_r(d[k]["pv_terminal"], 2))
        if k.startswith("comps"):
            x.update(peer_median=_r(d[k]["median"], 2), peers=[p["ticker"] for p in d[k]["peers"]])
        if k == "nav":
            x.update(cap_rate=_r(d[k]["cap_rate"]), noi_m=_r(d[k]["noi"], 0), net_debt_m=_r(d[k]["net_debt"], 0))
        methods[k] = x
    return {
        "company": {"name": cd.profile.name, "ticker": cd.profile.ticker, "sic": cd.profile.sic_description,
                    "reporting_currency": cd.profile.reporting_currency, "latest_fiscal_year": fv.period},
        "price": _r(vd.price, 2),
        "calendar": calendar_of(report),
        "toolkit": {"toolkit": fv.toolkit, "why_no_dcf": fv.why_no_dcf},
        "historicals_usd_m": {line: {p: _r(h.v(line, p), 2) for p in periods} for line in FS_LINES[fv.toolkit]},
        "sector_metrics": {m.key: {"label": m.label, "computed": _r(m.value.value),
                                   "reported": _r(m.reported.value) if m.reported is not None else None}
                           for m in fv.metrics},
        "cost_of_equity": {"cost_of_equity": _r(fv.cost_of_equity.value), "risk_free": _r(report.inputs.risk_free.value),
                           "erp": _r(report.inputs.erp.value), "crp": _r(report.inputs.crp.value),
                           "long_run_growth": _r(fv.growth.value),
                           "normalised_return": _r(fv.normalised_return.value) if fv.normalised_return else None,
                           "book_value_per_share_used": _r(fv.base_per_share.value, 2) if fv.base_per_share else None},
        "methods": methods,
        "verdict": {"fair_value": _r(vd.fair_value, 2), "gap": _r(vd.gap), "verdict": vd.verdict,
                    "confidence": vd.confidence, "components": components_of(vd),
                    "weights": {("sum_of_the_parts" if k == "dcf" and getattr(vd, "dcf_is_sotp", False) else k): _r(w)
                                for k, w in vd.weights_used.items()}},
        "analyst_targets": report.analyst_targets,
        "flags": [{"level": f.level, "code": f.code, "message": f.message} for f in report.flags],
        "rule_thresholds": RULE_THRESHOLDS,
        "research": research or {},
    }


def build_summary(report, research: dict | None = None) -> dict:
    if getattr(report, "financial", None) is not None:
        return financial_summary(report, research)
    cd, v, vd = report.company, report.valuation, report.verdict
    h = cd.historicals_usd
    last = h.fy_labels[-1]
    periods = h.fy_labels[-4:] + ([h.ltm.label] if h.ltm else [])
    lines = ["revenue", "operating_income", "net_income_attributable", "ebitda", "fcf", "sbc", "cash_and_investments",
             "debt_for_valuation", "net_debt"]
    hist = {line: {p: _r(h.v(line, p), 1) for p in periods} for line in lines}
    a = cd.analysis
    metrics = {m: {p: _r(a.m(m, p)) for p in periods} for m in
               ("revenue_growth", "operating_margin", "fcf_margin", "roic", "roe", "sbc_pct_revenue",
                "net_debt_to_ebitda", "interest_cover", "fcf_conversion")}
    plan = v.plan
    drivers = {d.name: {"label": d.label, "history": _r(d.history.value) if d.history else None,
                        "consensus": _r(d.consensus.value) if d.consensus else None,
                        "industry": _r(d.industry.value) if d.industry else None,
                        "chosen": _r(d.chosen.value), "path": [_r(x) for x in d.path], "source": d.source,
                        "confidence": d.confidence} for d in plan.drivers.values()}
    comps = None
    if report.comps:
        comps = {"peers": [p.ticker for p in report.comps.peers], "selection": report.comps.selection_steps,
                 "multiples": {m.label: {"peer_median": _r(m.median, 2), "company": _r(m.company_value, 2),
                                         "implied_price": _r(m.implied_price, 2)} for m in report.comps.multiples.values()},
                 "benchmarks": {b["label"]: {"company": _r(b["company"]), "peer_median": _r(b["peer_median"]),
                                             "percentile": _r(b["percentile"], 2)} for b in report.comps.benchmarks.values()}}
    return {
        "company": {"name": cd.profile.name, "ticker": cd.profile.ticker, "sic": cd.profile.sic_description,
                    "reporting_currency": cd.profile.reporting_currency, "latest_fiscal_year": last},
        "price": _r(vd.price, 2),
        "calendar": calendar_of(report),
        "stage": {"stage": v.classification.stage_label, "reason": v.classification.stage_reason,
                  "evidence": {k: _r(x) if isinstance(x, (int, float)) and not isinstance(x, bool) else x
                               for k, x in v.classification.evidence.items()}},
        "cycle": {k: _r(x) if isinstance(x, float) else x for k, x in v.cycle.items()},
        "historicals_usd_m": hist,
        "metrics": metrics,
        "wacc": {"wacc": _r(v.wacc.wacc.value), "cost_of_equity": _r(v.wacc.cost_of_equity.value),
                 "beta": _r(v.wacc.beta.value, 2), "risk_free": _r(report.inputs.risk_free.value),
                 "erp": _r(report.inputs.erp.value), "crp": _r(report.inputs.crp.value)},
        "forecast_drivers": drivers,
        "terminal": {"growth": _r(plan.terminal_growth.value), "roic": _r(plan.terminal_roic.value)},
        "dcf": None if not v.dcf else {
            "value_per_share": _r(v.per_us_share(v.dcf.value_per_share), 2),
            # every DCF figure, produced once by the engine (per US share): quote these and no other DCF value
            "figures": {k: _r(x, 2) for k, x in (getattr(v, "dcf_figures", None) or {}).items()},
            "left_out_of_the_blend": bool(getattr(v, "model_fit_failed", False)),
            "tv_share_of_ev": _r(v.dcf.tv_share_of_ev, 3), "enterprise_value_m": _r(v.dcf.enterprise_value, 0),
            "scenarios": {s.scenario.name: {"value": _r(v.per_us_share(s.value_per_share), 2),
                                            "probability": s.scenario.probability,
                                            "assumptions": s.scenario.describe()} for s in v.scenarios},
            "structural_case_value": _r(v.per_us_share(v.structural_case.value_per_share), 2)
            if v.structural_case else None},
        "reverse_dcf": v.reverse,
        "comps": comps,
        "historical_multiples": {hm.label: {"low": _r(hm.low, 2), "median": _r(hm.median, 2), "high": _r(hm.high, 2),
                                            "current": _r(hm.current, 2), "implied_price": _r(hm.implied_price, 2)}
                                 for hm in report.history.values()},
        "verdict": {"fair_value": _r(vd.fair_value, 2), "gap": _r(vd.gap), "verdict": vd.verdict,
                    "confidence": vd.confidence, "components": components_of(vd),
                    "weights": {("sum_of_the_parts" if k == "dcf" and getattr(vd, "dcf_is_sotp", False) else k): _r(w)
                                for k, w in vd.weights_used.items()},
                    "blend_fair_value": _r(getattr(vd, "blend_fair_value", None), 2),
                    "headline_is_the_scenario_weighted_dcf": bool(getattr(vd, "fallback", None))},
        "analyst_targets": report.analyst_targets,
        "flags": [{"level": f.level, "code": f.code, "message": f.message} for f in report.flags],
        # the brief's own thresholds, so a desk may say "above the 80% limit" without failing the number guard
        "rule_thresholds": RULE_THRESHOLDS,
        "research": research or {},
    }
