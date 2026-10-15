"""Compact, rounded summary of the computed results that the AI desks read. The same numbers form the number
guard's allowed set, so the AI can only quote what is here (or in the filing quotes it is given)."""
from __future__ import annotations


def _r(x, nd=4):
    return None if x is None else round(float(x), nd)


def build_summary(report, research: dict | None = None) -> dict:
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
                    "confidence": vd.confidence, "components": {k: _r(x, 2) for k, x in vd.components.items()},
                    "weights": {k: _r(w) for k, w in vd.weights_used.items()}},
        "analyst_targets": report.analyst_targets,
        "flags": [{"level": f.level, "code": f.code, "message": f.message} for f in report.flags],
        "research": research or {},
    }
