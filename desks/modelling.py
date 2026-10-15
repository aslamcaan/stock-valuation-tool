"""Modelling desk: everything numeric after the data desk (DCF engine, comps, historical multiples, estimate
revisions, verdict, confidence, football field, assumptions and provenance). Code only, no AI.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from data_desk.builder import CompanyData
from data_desk.history_data import price_series, week52, year_points
from data_desk.peers import gather_peers, latest_period, metrics_from, next_fy_eps, peer_metrics
from data_desk.valuation_inputs import build_engine_inputs, crp_from_filing_geography, one_off_adjustments
from engine.sotp import Segment
from engine.comps import CompanyMetrics, CompsResult, run_comps, select_peers
from engine.flags import AMBER, INFO, RED, Flag, sort_flags
from engine.history_multiples import HistoryResult, history_multiples, implied_price
from engine.valuation import EngineInputs, Valuation, value_company
from engine.values import PER_SHARE, RATIO, Value
from engine.verdict import Bar, Verdict, blend, confidence, football_field


@dataclass
class ValuationReport:
    company: CompanyData
    inputs: EngineInputs
    valuation: Valuation
    comps: CompsResult | None
    history: dict[str, HistoryResult]
    revisions: dict
    verdict: Verdict
    football: list[Bar]
    analyst_targets: dict | None
    week52: tuple[float, float] | None
    flags: list[Flag]
    trace: dict[str, Value]
    assumptions: list[dict]
    sources: list[dict]
    notes: list[str] = field(default_factory=list)


def _v(x: float | None, formula: str, unit: str = PER_SHARE) -> Value:
    return Value(x, "USD" if unit == PER_SHARE else None, unit, "current", "calculated", formula=formula)


def company_metrics(cd: CompanyData, svc, ei: EngineInputs) -> CompanyMetrics:
    h = cd.historicals_usd
    eps = next_fy_eps(svc, cd.profile.ticker, ei.valuation_date.isoformat()) if cd.historicals.currency == "USD" else None
    return metrics_from(h, cd.analysis, ticker=cd.profile.ticker, name=cd.profile.name, sic=cd.profile.sic,
                        market_cap=ei.market_cap.value, price=ei.price.value, forward_eps=eps,
                        source=f"SEC XBRL ({latest_period(h)})")


def segments_from_research(svc, cd: CompanyData, research: dict, notes: list[str]) -> list[Segment]:
    """Segments with an EV/Sales multiple from the research desk's US-listed comparables (computed by code)."""
    segs = research.get("segments") or []
    if len(segs) < 2 or cd.historicals.currency != "USD":
        return []
    total = cd.historicals.v("revenue", cd.historicals.fy_labels[-1]) or 0
    if total <= 0 or sum(s.get("revenue_millions") or 0 for s in segs) < 0.9 * total:
        notes.append("SOTP: segment revenues from the filing cover less than 90% of revenue")
        return []
    rows = {r["ticker"]: r for r in svc.edgar.company_tickers().payload}
    out = []
    for s in segs:
        mults, used = [], []
        for t in (s.get("comparable_us_tickers") or [])[:3]:
            m, _ = peer_metrics(svc, t.upper(), rows)
            ev = m.multiples()["ev_sales"] if m else None
            if ev:
                mults.append(ev)
                used.append(f"{t.upper()} {ev:.1f}x")
        if not mults or not s.get("revenue_millions"):
            notes.append(f"SOTP: no usable comparable multiple for segment {s.get('name')}")
            return []
        mults.sort()
        mid = mults[len(mults) // 2] if len(mults) % 2 else (mults[len(mults) // 2 - 1] + mults[len(mults) // 2]) / 2
        out.append(Segment(s["name"], s["revenue_millions"], s.get("profit_millions"), metric="EV/Sales",
                           metric_value=s["revenue_millions"], multiple=mid,
                           multiple_source="median EV/Sales of " + ", ".join(used)))
    return out


def run_modelling(cd: CompanyData, svc, valuation_date: date | None = None, overrides: dict | None = None,
                  progress=None, peers: list[CompanyMetrics] | None = None, research: dict | None = None
                  ) -> ValuationReport:
    say = progress or (lambda m: None)
    today = valuation_date or date.today()
    ei, notes = build_engine_inputs(cd, svc, today, overrides)
    extra_flags: list[Flag] = []
    if research:
        geo_crp = crp_from_filing_geography(svc, research.get("geographic_mix") or [], "annual report")
        if geo_crp is not None:
            ei.crp = geo_crp
        if cd.historicals.currency == "USD":
            ei.one_off_adjustments = one_off_adjustments(research, cd.historicals.fy_labels)
        say("Valuing segments for the sum of the parts")
        ei.segments = segments_from_research(svc, cd, research, notes)
        conv = research.get("convertible_debt") or {}
        if conv.get("present") and not any(f.code == "convertible_debt" for f in cd.flags):
            extra_flags.append(Flag(AMBER, "convertible_debt", "Convertible debt outstanding",
                                    f"The annual report describes convertible notes: \"{conv.get('quote', '')[:200]}\". "
                                    "Conversion would dilute shareholders beyond the diluted share count.", None, {}))
        sc = research.get("share_classes") or {}
        if sc.get("multiple") and not any(f.code == "multiple_share_classes" for f in cd.flags):
            extra_flags.append(Flag(AMBER, "multiple_share_classes", "Multiple share classes",
                                    f"{sc.get('description', '')} Quote: \"{sc.get('quote', '')[:200]}\"", None, {}))
    say("Classifying the company and building the forecast")
    v = value_company(ei)
    flags: list[Flag] = list(cd.flags) + list(v.flags) + extra_flags
    adr = ei.adr_ratio
    shares = v.diluted_shares.value
    bridge = sum(x.value for _, x in v.bridge)

    # --- comps ----------------------------------------------------------------------------------------------
    say("Selecting peers and computing multiples")
    me = company_metrics(cd, svc, ei)
    if peers is None:
        peers, peer_notes = gather_peers(svc, cd.profile.ticker, progress=say)
        notes += peer_notes
    chosen, steps = select_peers(me, peers)
    comps = run_comps(me, chosen, steps, shares, bridge, adr) if chosen else None
    if comps is None or len(chosen) < 5:
        flags.append(Flag(AMBER, "few_peers", "Fewer than 5 comparable companies",
                          f"Only {len(chosen)} usable peers after widening ({'; '.join(steps)}).", None,
                          {"peers": len(chosen)}))
    elif len(steps) > 1:
        flags.append(Flag(INFO, "peers_widened", "Peer filter widened",
                          f"Peer set widened to reach 5: {'; '.join(steps)}.", None, {}))

    # --- historical multiples ---------------------------------------------------------------------------------
    say("Computing historical multiples")
    closes, price_src, splits = price_series(svc, cd.profile.ticker, today - timedelta(days=365 * 6 + 30))
    pts = year_points(cd.historicals_usd, closes, adr, splits)
    current_metrics = {"revenue": me.revenue, "ebitda": me.ebitda, "fcf": me.fcf, "net_income": me.net_income}
    hist = history_multiples(pts, me.multiples(), current_metrics, shares, bridge, adr)
    w52 = week52(closes, today)

    # --- estimate revisions (own snapshots) ---------------------------------------------------------------------
    est = svc.market.analyst_estimates(cd.profile.ticker)
    rows = []
    if est.available:
        for r in est.data:
            rows.append({"fiscal_year_end": r.get("date", "")[:10], "revenue_avg": r.get("revenueAvg"),
                         "eps_avg": r.get("epsAvg"), "analysts": r.get("numAnalystsRevenue"), "source": est.source})
        svc.store.save_snapshot(cd.profile.ticker, rows, today)
    revisions = svc.store.revisions(cd.profile.ticker, today, rows) if rows else \
        {d: {"available": False, "reason": "no analyst consensus available"} for d in (30, 60, 90)}

    # --- verdict ----------------------------------------------------------------------------------------------------
    dcf_v = v.per_us_share(v.scenario_value)
    comps_v = comps.implied_price if comps else None
    hist_v = implied_price(hist)
    sotp_v = v.per_us_share(v.sotp.value_per_share) if v.sotp.applicable else None
    weights = (overrides or {}).get("blend_weights")
    verdict = blend({"dcf": dcf_v, "comps": comps_v, "history": hist_v}, ei.price.value, weights, sotp_v)
    pt = svc.market.price_target(cd.profile.ticker)
    targets = pt.data if pt.available else None
    disp = None
    for c in ei.consensus[:1]:
        if c.revenue and c.revenue_high and c.revenue_low:
            disp = (c.revenue_high - c.revenue_low) / c.revenue
    all_flags = sort_flags(flags)
    # consensus and peers have their own signals, so they are not counted again in completeness;
    # flags are counted once per code (not once per period)
    key_inputs = [hist_v is not None, cd.historicals.ltm is not None, ei.industry.unlevered_beta is not None,
                  "geography unavailable" not in (ei.crp.note or "")]
    level, reasons = confidence(verdict, estimate_dispersion=disp,
                                red_flags=len({f.code for f in all_flags if f.level == RED}),
                                amber_flags=len({f.code for f in all_flags if f.level == AMBER and f.code != "few_peers"}),
                                tv_share=v.dcf.tv_share_of_ev if v.dcf else None,
                                completeness=sum(key_inputs) / len(key_inputs),
                                peers_meet_brief_filter=bool(comps) and len(steps) <= 3)
    verdict.confidence, verdict.confidence_reasons = level, reasons
    bear, base, bull = (v.per_us_share(s.value_per_share) for s in v.scenarios) if len(v.scenarios) == 3 else (None,) * 3
    football = football_field(dcf_bear=bear, dcf_base=base, dcf_bull=bull, comps=comps.multiples if comps else {},
                              history=hist, analyst_targets=targets, week52=w52, sotp=sotp_v)

    # --- trace registry for headline numbers ------------------------------------------------------------------------
    trace: dict[str, Value] = {"price": ei.price, "wacc": v.wacc.wacc, "cost_of_equity": v.wacc.cost_of_equity,
                               "diluted_shares": v.diluted_shares, "terminal_growth": v.plan.terminal_growth,
                               "terminal_roic": v.plan.terminal_roic}
    if dcf_v is not None:
        trace["dcf_value"] = _v(dcf_v, "probability-weighted bear / base / bull DCF value per US share: " + ", ".join(
            f"{s.scenario.name} {v.per_us_share(s.value_per_share):,.2f} x {s.scenario.probability:.0%}"
            for s in v.scenarios))
    if comps_v is not None:
        trace["comps_value"] = _v(comps_v, "median of implied prices: " + ", ".join(
            f"{m.label} {m.implied_price:,.2f} (peer median {m.median:.1f}x)" for m in comps.multiples.values()
            if m.implied_price is not None))
    if hist_v is not None:
        trace["history_value"] = _v(hist_v, "median of implied prices at 5-year median multiples: " + ", ".join(
            f"{h.label} {h.implied_price:,.2f} ({h.median:.1f}x)" for h in hist.values() if h.implied_price is not None))
    if verdict.fair_value is not None:
        trace["fair_value"] = _v(verdict.fair_value, "weighted blend: " + ", ".join(
            f"{k} {verdict.components[k]:,.2f} x {w:.0%}" for k, w in verdict.weights_used.items()))
        trace["gap"] = _v(verdict.gap, "fair value / price - 1", RATIO)

    report = ValuationReport(cd, ei, v, comps, hist, revisions, verdict, football, targets, w52, all_flags, trace,
                             assumptions_table(ei, v, verdict), sources(cd, ei, price_src), notes)
    say("Modelling complete")
    return report


def assumptions_table(ei: EngineInputs, v: Valuation, verdict: Verdict) -> list[dict]:
    """Every assumption with its value, source and whether the user can edit it."""
    rows = []

    def add(group, name, value, unit, source, editable=None, note=None):
        rows.append({"group": group, "name": name, "value": value, "unit": unit, "source": source,
                     "editable": editable, "note": note})

    w = v.wacc
    add("WACC", "Risk-free rate", ei.risk_free.value, "%", f"{ei.risk_free.source} ({ei.risk_free.period})")
    add("WACC", "Equity risk premium", ei.erp.value, "%", f"{ei.erp.source} ({ei.erp.period})")
    add("WACC", "Beta (used)", w.beta.value, "x", w.beta.source if w.beta.formula is None else
        "industry unlevered beta relevered at market D/E", "beta", w.beta.note)
    if ei.beta_regression:
        add("WACC", "Regression beta (reference)", ei.beta_regression.value, "x", ei.beta_regression.source)
    add("WACC", "Country risk premium", ei.crp.value, "%", ei.crp.source, None, ei.crp.note)
    add("WACC", "Pre-tax cost of debt", v.cost_of_debt_detail["pre_tax_cost_of_debt"].value, "%",
        "risk-free + synthetic-rating spread + country spread", None, v.cost_of_debt_detail.get("rating"))
    add("WACC", "Marginal tax rate", ei.marginal_tax.value, "%", ei.marginal_tax.source, None, ei.marginal_tax.note)
    add("WACC", "WACC", w.wacc.value, "%", "calculated", "wacc")
    for d in v.plan.drivers.values():
        add("Forecast", d.label, d.chosen.value, "x" if d.name == "sales_to_capital" else "%", d.source,
            {"revenue_growth": "revenue_growth", "operating_margin": "target_margin",
             "sales_to_capital": "sales_to_capital"}.get(d.name), f"confidence {d.confidence}")
    add("Terminal", "Terminal growth", v.plan.terminal_growth.value, "%", v.plan.terminal_growth.source,
        "terminal_growth", v.plan.terminal_growth.note)
    add("Terminal", "Terminal ROIC", v.plan.terminal_roic.value, "%", v.plan.terminal_roic.source, "terminal_roic",
        v.plan.terminal_roic.note)
    for s in v.scenarios:
        add("Scenarios", f"{s.scenario.name} ({s.scenario.probability:.0%})", s.scenario.probability, "%",
            s.scenario.describe())
    for k, wt in verdict.weights_used.items():
        add("Blend", f"Weight: {k}", wt, "%", "default 50/30/20, rescaled when a method is missing", "blend_weights")
    add("Shares", "Diluted shares (m)", v.diluted_shares.value, "m", v.diluted_shares.formula or "reported", None,
        v.diluted_shares.note)
    return rows


def sources(cd: CompanyData, ei: EngineInputs, price_src: str) -> list[dict]:
    out = []
    lf = cd.historicals.latest_annual_filing
    if lf:
        out.append({"source": "SEC EDGAR", "what": f"Financial statements ({cd.historicals.taxonomy} XBRL)",
                    "detail": f"latest annual {lf['form']} filed {lf['filed']} ({lf['accn']})",
                    "fetched_at": next((v.fetched_at for v in cd.historicals.lines.get("revenue", {}).values()
                                        if v.fetched_at), None)})
    out.append({"source": ei.price.source, "what": "Share price", "detail": ei.price.period,
                "fetched_at": ei.price.fetched_at})
    out.append({"source": ei.risk_free.source, "what": "Risk-free rate", "detail": ei.risk_free.period,
                "fetched_at": ei.risk_free.fetched_at})
    out.append({"source": ei.erp.source, "what": "Equity risk premium", "detail": ei.erp.period,
                "fetched_at": ei.erp.fetched_at})
    if ei.industry.unlevered_beta:
        out.append({"source": ei.industry.unlevered_beta.source, "what": "Industry beta, margins, growth",
                    "detail": ei.industry.how, "fetched_at": ei.industry.unlevered_beta.fetched_at})
    out.append({"source": ei.crp.source, "what": "Country risk premium", "detail": ei.crp.note,
                "fetched_at": ei.crp.fetched_at})
    out.append({"source": "Price history", "what": "Historical multiples, 52-week range", "detail": price_src,
                "fetched_at": None})
    if ei.consensus:
        out.append({"source": ei.consensus[0].source, "what": "Analyst consensus", "detail":
                    f"{len(ei.consensus)} fiscal years", "fetched_at": ei.consensus[0].fetched_at})
    return out


__all__ = ["ValuationReport", "run_modelling"]
