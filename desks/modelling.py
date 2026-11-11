"""Modelling desk: everything numeric after the data desk (DCF engine, comps, historical multiples, estimate
revisions, verdict, confidence, football field, assumptions and provenance). Code only, no AI.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, timedelta

from data_desk import checks
from data_desk.builder import CompanyData
from data_desk.xbrl import fy_label
from data_desk.history_data import price_series, week52, year_points
from data_desk.peers import gather_peers, latest_period, metrics_from, next_fy_eps, peer_metrics
from data_desk.segments import match_names
from data_desk.valuation_inputs import build_engine_inputs, crp_from_filing_geography, one_off_adjustments
from engine.classify import CORPORATE, CYCLICAL, toolkit_for_sic
from engine.financials import FinancialError, FinancialValuation, FinInputs, method_label, value_financial
from engine.sotp import Segment
from engine.comps import (MIN_PEERS, NM_ABOVE, CompanyMetrics, CompsResult, mid_cycle_metrics, run_comps,
                          select_peers)
from engine.flags import AMBER, INFO, RED, Flag, sort_flags
from engine.history_multiples import HistoryResult, history_multiples, implied_price
from engine.valuation import EngineInputs, Valuation, ValuationError, value_company
from engine.values import PER_SHARE, RATIO, Value
from engine.verdict import Bar, Verdict, blend, confidence, football_field


@dataclass
class ValuationReport:
    company: CompanyData
    inputs: EngineInputs
    valuation: Valuation | None          # corporate toolkit (DCF); None for banks, insurers and REITs
    comps: CompsResult | None
    history: dict[str, HistoryResult]
    revisions: dict
    verdict: Verdict
    football: list[Bar]
    analyst_targets: dict | None
    week52: tuple[float, float] | None
    flags: list[Flag]
    company_metrics: CompanyMetrics | None
    trace: dict[str, Value]
    assumptions: list[dict]
    sources: list[dict]
    notes: list[str] = field(default_factory=list)
    financial: FinancialValuation | None = None  # bank / insurer / REIT toolkit

    @property
    def toolkit(self) -> str:
        fin = getattr(self, "financial", None)  # reports saved before the financial toolkits have no field
        return fin.toolkit if fin is not None else CORPORATE


def _v(x: float | None, formula: str, unit: str = PER_SHARE) -> Value:
    return Value(x, "USD" if unit == PER_SHARE else None, unit, "current", "calculated", formula=formula)


def company_metrics(cd: CompanyData, svc, ei: EngineInputs) -> CompanyMetrics:
    h = cd.historicals_usd
    eps = next_fy_eps(svc, cd.profile.ticker, ei.valuation_date.isoformat()) if cd.historicals.currency == "USD" else None
    return metrics_from(h, cd.analysis, ticker=cd.profile.ticker, name=cd.profile.name, sic=cd.profile.sic,
                        market_cap=ei.market_cap.value, price=ei.price.value, forward_eps=eps,
                        source=f"SEC XBRL ({latest_period(h)})")


def provider_flags(notes: list[str]) -> list[Flag]:
    """An amber flag when a market-data provider refused requests during the run (e.g. FMP's daily limit): the
    report then rests on fallbacks (peers from SEC frames, history instead of consensus), so it says so up front."""
    hit = [n for n in notes if "rate limited" in n or "HTTP 429" in n]
    if not hit:
        return []
    return [Flag(AMBER, "provider_unavailable", "Market data provider unavailable during this run",
                 "A data provider refused requests while this report ran (" + hit[0].split(";")[0][:120] + "). "
                 "Fallbacks were used where they exist: peers from SEC data, the price from Tiingo, the forecast from "
                 "history instead of analyst consensus. Re-run the report later for the full data.", None, {})]


def partial_inputs(ei, closes) -> list[str]:
    """Core inputs that are missing from this run (the report then rests on fallbacks)."""
    missing = []
    if not ei.consensus:
        missing.append("analyst consensus")
    if not closes:
        missing.append("price history")
    return missing


def top_notes(flags: list[Flag], notes: list[str], missing: list[str]) -> list[str]:
    """Plain-English lines printed at the top of the report: a partial run (a provider refused requests and a core
    input is missing) and any red data-check flag, which the rest of the report would otherwise bury."""
    out = []
    if missing and provider_flags(notes):
        out.append("Partial report: the market-data provider refused requests and " + " and ".join(missing)
                   + (" is" if len(missing) == 1 else " are") + " missing, so the forecast and multiples rest on "
                   "fallbacks. Confidence is Low. Re-run the report later for the full data.")
    reds = [f for f in flags if f.level == RED]
    if reds:
        out.append("Data check failed (red flag): " + "; ".join(
            f"{f.title}" + (f" ({f.period})" if f.period else "") for f in reds[:3]) + ". Confidence is lowered.")
    return out


def _median(xs: list[float]) -> float:
    xs = sorted(xs)
    k = len(xs) // 2
    return xs[k] if len(xs) % 2 else (xs[k - 1] + xs[k]) / 2


def xbrl_segments(svc, cd: CompanyData) -> tuple[str, dict, str] | None:
    """(fiscal year end, {label: row}, source) for the latest annual report's XBRL segment note, or None."""
    from data_desk.segments import instance_xml, latest_year, segment_facts
    try:
        filings = svc.edgar.filings(cd.profile.cik, forms={"10-K", "20-F", "40-F"})
    except Exception:  # noqa: BLE001 - the research desk's reading is the fallback
        return None
    if not filings:
        return None
    f = filings[0]
    xml = instance_xml(svc, cd.profile.cik, f)
    if xml is None:
        return None
    try:
        got = latest_year(segment_facts(xml))
    except Exception:  # noqa: BLE001 - malformed instance: fall back
        return None
    if got is None:
        return None
    end, rows, _ = got
    return end, rows, f"SEC XBRL segment note, {f.form} filed {f.filing_date}"


def _segment_multiple(svc, rows: dict, tickers: list[str], key: str) -> tuple[float | None, list[str]]:
    """Median EV/EBIT ('ev_ebit') or EV/Sales ('ev_sales') of up to three US-listed comparables (not-meaningful
    values above the comps cut-off are left out)."""
    vals, used = [], []
    for t in tickers[:3]:
        m, _ = peer_metrics(svc, t.upper(), rows)
        if m is None:
            continue
        if key == "ev_ebit":
            x = m.ev / m.operating_income if m.ev and m.operating_income and m.operating_income > 0 else None
            cap = NM_ABOVE["ev_ebitda"]
        else:
            x, cap = m.multiples()["ev_sales"], NM_ABOVE["ev_sales"]
        if x is not None and 0 < x <= cap:
            vals.append(x)
            used.append(f"{t.upper()} {x:.1f}x")
    return (_median(vals), used) if vals else (None, used)


def segments_from_research(svc, cd: CompanyData, research: dict, notes: list[str]) -> list[Segment]:
    """Segments for the sum of the parts. Revenue and operating income come from the filing's XBRL segment note
    when tagged (else from the research desk's reading of the annual report); names and US-listed comparables come
    from the research desk. A segment with positive operating income is valued on its comparables' median EV/EBIT
    (margins are why segments are valued apart), otherwise on EV/Sales. Costs not allocated to any segment are
    capitalised at the segments' average EV/EBIT and deducted, so the parts do not add up to more than the whole."""
    segs = research.get("segments") or []
    if cd.historicals.currency != "USD":
        notes.append(f"SOTP: not applied to {cd.historicals.currency} reporting (segment comparables are US-listed)")
        return []
    h = cd.historicals
    xb = xbrl_segments(svc, cd)
    fy = h.fy_labels[-1]
    source = "research desk reading of the annual report"
    if xb is not None:
        end, xrows, source = xb
        fy = next((p.label for p in h.periods if p.kind == "FY"
                   and abs((p.end - date.fromisoformat(end)).days) <= 20), None) or fy
        named = match_names(xrows, segs)
        unmatched = {k: r for k, r in xrows.items() if k not in named}
        if unmatched and research.get("segments_unverified"):  # names confirmed by XBRL, so the comparables stand
            extra = match_names(unmatched, research["segments_unverified"])
            named.update(extra)
            if extra:
                notes.append("SOTP: comparables for " + ", ".join(sorted(extra)) + " from the research desk, whose "
                             "quote for the segment could not be verified; the segment names match the XBRL note")
        items = [{"name": named[k]["name"] if k in named else k, "revenue": r["revenue"],
                  "profit": r.get("operating_income"), "growth": r.get("growth"),
                  "tickers": (named.get(k) or {}).get("comparable_us_tickers") or []} for k, r in xrows.items()]
    else:
        if not any(x.get("revenue_millions") for x in segs):
            notes.append("SOTP: the research desk found segment profits but not segment revenues in the filing"
                         if segs else "SOTP: the annual report gave fewer than two segments")
            return []
        items = [{"name": x["name"], "revenue": x.get("revenue_millions"), "profit": x.get("profit_millions"),
                  "growth": None, "tickers": x.get("comparable_us_tickers") or []} for x in segs]
    if len(items) < 2:
        notes.append("SOTP: the annual report gave fewer than two segments")
        return []
    total = h.v("revenue", fy) or 0
    if total <= 0 or sum(x["revenue"] or 0 for x in items) < 0.9 * total:
        notes.append("SOTP: segment revenues from the filing cover less than 90% of revenue")
        return []
    rows = {r["ticker"]: r for r in svc.edgar.company_tickers().payload}
    out = []
    for x in items:
        if not x["tickers"]:
            notes.append(f"SOTP: no comparable companies for segment {x['name']}")
            return []
        on_profit = x["profit"] is not None and x["profit"] > 0
        mult, used = _segment_multiple(svc, rows, x["tickers"], "ev_ebit" if on_profit else "ev_sales")
        if mult is None and on_profit:  # comparables without positive EBIT: fall back to sales
            on_profit = False
            mult, used = _segment_multiple(svc, rows, x["tickers"], "ev_sales")
        if mult is None or not x["revenue"]:
            notes.append(f"SOTP: no usable comparable multiple for segment {x['name']}")
            return []
        metric = "EV/EBIT" if on_profit else "EV/Sales"
        out.append(Segment(x["name"], x["revenue"], x["profit"], x["growth"], metric=metric,
                           metric_value=x["profit"] if on_profit else x["revenue"], multiple=mult,
                           multiple_source=f"median {metric} of " + ", ".join(used) + f"; segment figures: {source}"))
    consolidated = h.v("operating_income", fy)
    if all(sg.metric == "EV/EBIT" for sg in out) and consolidated is not None:
        corporate = consolidated - sum(sg.profit for sg in out)
        if corporate < 0:
            avg = sum(sg.metric_value * sg.multiple for sg in out) / sum(sg.metric_value for sg in out)
            out.append(Segment("Corporate and unallocated costs", 0.0, corporate, metric="EV/EBIT",
                               metric_value=corporate, multiple=avg,
                               multiple_source=f"capitalised at the segments' average EV/EBIT: consolidated "
                                               f"operating income {consolidated:,.0f} less segments' "
                                               f"{sum(sg.profit for sg in out):,.0f} ({fy})"))
    notes.append(f"SOTP segment figures: {source}")
    return out


def _kpi_label(x: dict) -> str | None:
    """FY label the tool uses for a KPI value: from the period-end date when given (non-December years are
    named differently by different companies), else the last year in the fiscal-year text ("FY2024/25" -> 2025)."""
    try:
        return fy_label(date.fromisoformat((x.get("period_end") or "")[:10]))
    except ValueError:
        pass
    t = x.get("fiscal_year") or ""
    m = re.search(r"((?:19|20)\d{2})\s*[/-]\s*(\d{2})\b", t)
    if m:
        return f"FY{m.group(1)[:2]}{m.group(2)}"
    ys = re.findall(r"(?:19|20)\d{2}", t)
    return f"FY{ys[-1]}" if ys else None


def kpi_flags(cd: CompanyData, vk: dict) -> list[Flag]:
    """Revenue growth vs the reported volume KPI (e.g. Gross Bookings), from figures verified in the filing."""
    series = {}
    for x in vk.get("values") or []:
        label = _kpi_label(x)
        if label and label in cd.historicals.fy_labels and x.get("value_millions"):
            series[label] = float(x["value_millions"])
    if len(series) < 2 or not vk.get("name"):
        return []
    return checks.kpi_divergence(cd.historicals, vk["name"], series)


def run_modelling(cd: CompanyData, svc, valuation_date: date | None = None, overrides: dict | None = None,
                  progress=None, peers: list[CompanyMetrics] | None = None, research: dict | None = None
                  ) -> ValuationReport:
    say = progress or (lambda m: None)
    today = valuation_date or date.today()
    ei, notes = build_engine_inputs(cd, svc, today, overrides)
    extra_flags: list[Flag] = []
    ind = getattr(ei, "industry", None)
    how = getattr(ind, "how", None) or "matched"  # no industry data (test fakes): nothing to flag
    if how.startswith("manual"):
        extra_flags.append(Flag(INFO, "industry_manual", "Industry mapped manually",
                                f"Industry beta, margin and growth use '{ei.industry.name}' ({how}).",
                                None, {"industry": ei.industry.name}))
    elif not how.startswith("matched"):
        extra_flags.append(Flag(AMBER, "industry_proxy", "Industry benchmarks are a proxy",
                                f"The company is not in Damodaran's company list, so industry beta, margin and "
                                f"growth use '{ei.industry.name}' ({how}). Check the industry fits the business.",
                                None, {"industry": ei.industry.name}))
    if research:
        geo_crp = crp_from_filing_geography(svc, research.get("geographic_mix") or [], "annual report")
        if geo_crp is not None:
            ei.crp = geo_crp
        if cd.historicals.currency == "USD":
            ei.one_off_adjustments = one_off_adjustments(
                research, cd.historicals.fy_labels,
                {p: cd.historicals.v("operating_income", p) for p in cd.historicals.fy_labels}, notes)
        say("Valuing segments for the sum of the parts")
        before = len(notes)
        ei.segments = segments_from_research(svc, cd, research, notes)
        if not ei.segments:
            ei.segments_reason = next((n.removeprefix("SOTP: ") for n in notes[before:] if n.startswith("SOTP: ")),
                                      "the annual report gave fewer than two segments")
        conv = research.get("convertible_debt") or {}
        if conv.get("present") and not any(f.code == "convertible_debt" for f in cd.flags):
            extra_flags.append(Flag(AMBER, "convertible_debt", "Convertible debt outstanding",
                                    f"The annual report describes convertible notes: \"{conv.get('quote', '')[:200]}\". "
                                    "Conversion would dilute shareholders beyond the diluted share count.", None, {}))
        extra_flags += kpi_flags(cd, research.get("volume_kpi") or {})
        sc = research.get("share_classes") or {}
        if sc.get("multiple") and not any(f.code == "multiple_share_classes" for f in cd.flags):
            extra_flags.append(Flag(AMBER, "multiple_share_classes", "Multiple share classes",
                                    f"{sc.get('description', '')} Quote: \"{sc.get('quote', '')[:200]}\"", None, {}))
    toolkit, _ = toolkit_for_sic(cd.profile.sic)
    if toolkit != CORPORATE:
        return run_financial(cd, svc, ei, toolkit, today, notes, overrides or {}, peers, say, extra_flags)
    say("Classifying the company and building the forecast")
    v = value_company(ei)
    stops = [f for f in v.flags if f.is_hard_stop]
    if stops:  # e.g. terminal growth at or above WACC: refuse to value, naming the line that broke
        raise ValuationError("Hard stop: " + "; ".join(f"{f.title}: {f.message}" for f in stops))
    flags: list[Flag] = list(cd.flags) + list(v.flags) + extra_flags
    adr = ei.adr_ratio
    shares = v.diluted_shares.value
    # comps and historical multiples: peer and past EVs net only cash, so their multiples already price any
    # investments; adding the company's investments again would count them twice
    bridge = sum(x.value for n, x in v.bridge if n != "Long-term investments")

    # --- comps ----------------------------------------------------------------------------------------------
    say("Selecting peers and computing multiples")
    me = company_metrics(cd, svc, ei)
    if peers is None:
        peers, peer_notes = gather_peers(svc, cd.profile.ticker, progress=say)
        notes += peer_notes
    chosen, steps = select_peers(me, peers)
    norm, norm_note = None, ""
    if v.classification.stage == CYCLICAL and v.plan.drivers.get("operating_margin") is not None:
        got = mid_cycle_metrics(me, v.plan.drivers["operating_margin"].chosen.value, ei.marginal_tax.value)
        if got:
            norm, norm_note = got
            flags.append(Flag(INFO, "comps_mid_cycle", "Peer multiples applied to mid-cycle earnings", norm_note + ".",
                              None, {}))
    comps = run_comps(me, chosen, steps, shares, bridge, adr, normalised=norm, normalised_note=norm_note)         if chosen else None
    comps_usable = comps is not None and len(chosen) >= MIN_PEERS
    if not comps_usable:
        flags.append(Flag(AMBER, "few_peers", "Fewer than 5 comparable companies",
                          f"Only {len(chosen)} true peers (same 3-digit SIC or a named peer; {'; '.join(steps)}). "
                          "The comps value is shown but given no weight in the fair value.", None,
                          {"peers": len(chosen)}))
    elif len(steps) > 1:
        flags.append(Flag(INFO, "peers_widened", "Peer filter widened",
                          f"Peer set widened to reach 5: {'; '.join(steps)}.", None, {}))

    # --- historical multiples ---------------------------------------------------------------------------------
    say("Computing historical multiples")
    closes, price_src, splits = price_series(svc, cd.profile.ticker, today - timedelta(days=365 * 6 + 30))
    pts = year_points(cd.historicals_usd, closes, adr, splits)
    cm = norm or me  # a cyclical's historical multiples are applied to mid-cycle earnings too
    current_metrics = {"revenue": cm.revenue, "ebitda": cm.ebitda, "fcf": cm.fcf, "net_income": cm.net_income}
    hist = history_multiples(pts, me.multiples(), current_metrics, shares, bridge, adr)
    w52 = week52(closes, today)

    revisions = estimate_revisions(svc, cd.profile.ticker, today)

    # --- verdict ----------------------------------------------------------------------------------------------------
    dcf_v = None if v.model_fit_failed else v.per_us_share(v.scenario_value)  # one DCF figure: v.dcf_figures
    comps_v = comps.implied_price if comps_usable else None
    hist_v = implied_price(hist)
    sotp_v = v.per_us_share(v.sotp.value_per_share) if v.sotp.applicable else None
    weights = (overrides or {}).get("blend_weights")
    verdict = blend({"dcf": dcf_v, "comps": comps_v, "history": hist_v}, ei.price.value, weights, sotp_v,
                    dcf_value=dcf_v)
    pt = svc.market.price_target(cd.profile.ticker)
    targets = pt.data if pt.available else None
    disp = None
    for c in [c for c in ei.consensus if c.fiscal_year_end > today][:1]:  # the nearest year not yet ended
        if c.revenue and c.revenue_high and c.revenue_low:
            disp = (c.revenue_high - c.revenue_low) / c.revenue
    flags += checks.adr_ratio_applied(adr, v.per_us_share_factor)
    flags += checks.dilution_gap(ei.basic_shares.value, v.diluted_shares.value, v.diluted_shares.formula or "")
    all_flags = sort_flags(flags + provider_flags(notes))
    # consensus and peers have their own signals, so they are not counted again in completeness;
    # flags are counted once per code (not once per period)
    key_inputs = [hist_v is not None, cd.historicals.ltm is not None, ei.industry.unlevered_beta is not None,
                  "geography unavailable" not in (ei.crp.note or "")]
    level, reasons = confidence(verdict, estimate_dispersion=disp,
                                red_flags=len({f.code for f in all_flags if f.level == RED}),
                                amber_flags=len({f.code for f in all_flags if f.level == AMBER and f.code != "few_peers"}),
                                tv_share=v.dcf.tv_share_of_ev if v.dcf else None,
                                completeness=sum(key_inputs) / len(key_inputs),
                                peers_meet_brief_filter=comps_usable and len(steps) <= 3)
    verdict.confidence, verdict.confidence_reasons = level, reasons
    verdict.top_notes = top_notes(all_flags, notes, partial_inputs(ei, closes))
    if any(n.startswith("Partial report") for n in verdict.top_notes) and verdict.confidence != "Low":
        verdict.confidence = "Low"
        verdict.confidence_reasons = ["a core input is missing after the data provider refused requests"] + reasons
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
        trace["fair_value"] = _v(verdict.fair_value, ("scenario-weighted DCF (the blend was not used): "
                                                      + verdict.headline_note) if verdict.fallback else
                                 "weighted blend: " + ", ".join(
            f"{k} {verdict.components[k]:,.2f} x {w:.0%}" for k, w in verdict.weights_used.items()))
        trace["gap"] = _v(verdict.gap, "fair value / price - 1", RATIO)

    report = ValuationReport(cd, ei, v, comps, hist, revisions, verdict, football, targets, w52, all_flags, me, trace,
                             assumptions_table(ei, v, verdict), sources(cd, ei, price_src), notes)
    say("Modelling complete")
    return report


def refresh_headline_trace(model: ValuationReport) -> None:
    """Re-point the traced headline numbers at the verdict after it changed (the review desk took it off the blend)."""
    vd = model.verdict
    if vd.fair_value is None:
        return
    model.trace["fair_value"] = _v(vd.fair_value, ("scenario-weighted DCF (the blend was not used): "
                                                   + vd.headline_note) if vd.fallback else "weighted blend: " + ", ".join(
        f"{k} {vd.components[k]:,.2f} x {w:.0%}" for k, w in vd.weights_used.items()))
    model.trace["gap"] = _v(vd.gap, "fair value / price - 1", RATIO)


def estimate_revisions(svc, ticker: str, today: date) -> dict:
    """Consensus revisions over 30/60/90 days from the tool's own daily snapshots."""
    est = svc.market.analyst_estimates(ticker)
    rows = []
    if est.available:
        for r in est.data:
            rows.append({"fiscal_year_end": r.get("date", "")[:10], "revenue_avg": r.get("revenueAvg"),
                         "eps_avg": r.get("epsAvg"), "analysts": r.get("numAnalystsRevenue"), "source": est.source})
        svc.store.save_snapshot(ticker, rows, today)
    return svc.store.revisions(ticker, today, rows) if rows else \
        {d: {"available": False, "reason": "no analyst consensus available"} for d in (30, 60, 90)}


def reported_kpis_for(svc, cd: CompanyData, toolkit: str, period: str) -> tuple[dict[str, Value], list[str]]:
    """The company's own reported KPIs (CET1, combined ratio, FFO...) read from the latest annual report's text,
    each with its verbatim quote. Used only when that report covers the same fiscal year as the statements."""
    from data_desk.filings import annual_report_html
    from data_desk.fin_text import plain, reported_kpis
    cik = cd.profile.statements_cik
    filings = svc.edgar.filings(cik, forms={"10-K"})
    if not filings:
        return {}, ["no 10-K on file: reported KPIs not available"]
    f = filings[0]
    try:
        raw, fetched = annual_report_html(svc, cik, f)
    except Exception as exc:  # the metrics computed from XBRL still stand
        return {}, [f"annual report text unavailable ({type(exc).__name__}): reported KPIs not read"]
    fy = fy_label(date.fromisoformat(f.report_date)) if f.report_date else None
    if fy != period:
        return {}, [f"latest 10-K covers {fy}, statements run to {period}: reported KPIs not used"]
    src = f"{f.form} filed {f.filing_date} ({f.accession}), annual report text"
    out = {}
    for k, r in reported_kpis(plain(raw), toolkit, src).items():
        out[k] = Value(r.value, None if r.unit == RATIO else "USD", r.unit, period, "SEC EDGAR (10-K text)",
                       fetched_at=fetched, filing=src, note=f'quote: "{r.quote}"')
    return out, []


def _bars(toolkit: str, fv: FinancialValuation, inputs: FinInputs) -> list[Bar]:
    """Football field: each method re-run at cost of equity -1 / +1 point (peer multiples as computed)."""
    from dataclasses import replace as _replace
    alts: dict[str, list[float]] = {}
    for d in (-0.01, 0.01):
        try:
            alt = value_financial(_replace(inputs, overrides={**inputs.overrides,
                                                              "cost_of_equity": fv.cost_of_equity.value + d}))
        except FinancialError:
            continue
        for k, v in alt.methods.items():
            alts.setdefault(k, []).append(v.value)
    bars = []
    for k, v in fv.methods.items():
        xs = (alts.get(k, []) if not k.startswith("comps") else []) + [v.value]
        bars.append(Bar(method_label(k, toolkit), min(xs), max(xs), v.value,
                        "peer median" if k.startswith("comps") else "cost of equity +/- 1 point"))
    return bars


def run_financial(cd: CompanyData, svc, ei: EngineInputs, toolkit: str, today: date, notes: list[str],
                  overrides: dict, peers: list[CompanyMetrics] | None, say,
                  extra_flags: list[Flag] | None = None) -> ValuationReport:
    """Banks, insurers and REITs: no DCF (PROMPT.md section 8)."""
    say(f"{toolkit.capitalize()} toolkit: reading reported KPIs from the annual report")
    h = cd.historicals_usd
    period = h.fy_labels[-1]
    if cd.historicals.currency == "USD":
        reported, kpi_notes = reported_kpis_for(svc, cd, toolkit, period)
    else:
        reported, kpi_notes = {}, ["reported KPIs are read only from US$ annual reports"]
    notes += kpi_notes
    say("Selecting peers")
    me = company_metrics(cd, svc, ei)
    if peers is None:
        peers, peer_notes = gather_peers(svc, cd.profile.ticker, progress=say)
        notes += peer_notes
    # peer multiples only mean something within the same toolkit (no corporates in a bank's P/TBV median)
    chosen, steps = select_peers(me, [p for p in peers if toolkit_for_sic(p.sic or "")[0] == toolkit])
    beta = ei.industry.levered_beta if overrides.get("beta_choice", "industry") == "industry" else None
    beta = beta or ei.beta_regression
    if beta is None:
        raise ValuationError("Cannot value: no beta available (no industry beta and no regression beta).")
    shares = cd.historicals.get("shares_outstanding", period) or ei.basic_shares
    fin_in = FinInputs(toolkit, h, ei.price, shares, ei.adr_ratio, ei.risk_free, ei.erp, ei.crp, beta,
                       reported, chosen, overrides)
    say("Valuing on book, returns, dividends and peer multiples")
    try:
        fv = value_financial(fin_in)
    except FinancialError as exc:
        raise ValuationError(str(exc)) from exc
    # corporate key lines (revenue, operating income...) are not the lines this toolkit values on
    flags: list[Flag] = [f for f in cd.flags if f.code != "missing_key_line"] + list(fv.flags) +         list(extra_flags or [])
    if len(chosen) < 5:
        flags.append(Flag(AMBER, "few_peers", "Fewer than 5 comparable companies",
                          f"Only {len(chosen)} usable peers after widening ({'; '.join(steps)}).", None,
                          {"peers": len(chosen)}))
    closes, price_src, _ = price_series(svc, cd.profile.ticker, today - timedelta(days=400))
    w52 = week52(closes, today)
    revisions = estimate_revisions(svc, cd.profile.ticker, today)
    verdict = blend({k: v.value for k, v in fv.methods.items()}, ei.price.value, fv.weights)
    pt = svc.market.price_target(cd.profile.ticker)
    targets = pt.data if pt.available else None
    flags += checks.adr_ratio_applied(ei.adr_ratio or 1.0, fv.per_us_share_factor)
    all_flags = sort_flags(flags + provider_flags(notes))
    key = {"bank": ("cet1_ratio", "rote", "tbvps"), "insurer": ("combined_ratio", "roe", "bvps"),
           "reit": ("ffo_per_share", "affo_per_share", "noi")}[toolkit]
    have = [bool(fv.metric(k) and (fv.metric(k).reported is not None or fv.metric(k).value.value is not None))
            for k in key]
    level, reasons = confidence(verdict, estimate_dispersion=0.0,
                                red_flags=len({f.code for f in all_flags if f.level == RED}),
                                amber_flags=len({f.code for f in all_flags if f.level == AMBER and f.code != "few_peers"}),
                                tv_share=None, completeness=sum(have) / len(have),
                                peers_meet_brief_filter=len(chosen) >= 5 and len(steps) <= 3)
    verdict.confidence, verdict.confidence_reasons = level, reasons
    football = _bars(toolkit, fv, fin_in)
    if targets and targets.get("low") and targets.get("high"):
        football.append(Bar("Analyst price targets", targets["low"], targets["high"], targets.get("median"),
                            "low to high"))
    if w52:
        football.append(Bar("52-week trading range", w52[0], w52[1], None))
    trace: dict[str, Value] = {"price": ei.price, "cost_of_equity": fv.cost_of_equity, "long_run_growth": fv.growth}
    trace.update({f"method_{k}": v for k, v in fv.methods.items()})
    if fv.base_per_share is not None:
        trace["book_per_share"] = fv.base_per_share
    if verdict.fair_value is not None:
        trace["fair_value"] = _v(verdict.fair_value, "weighted blend: " + ", ".join(
            f"{method_label(k, toolkit)} {verdict.components[k]:,.2f} x {w:.0%}"
            for k, w in verdict.weights_used.items()))
        trace["gap"] = _v(verdict.gap, "fair value / price - 1", RATIO)
    report = ValuationReport(cd, ei, None, None, {}, revisions, verdict, football, targets, w52, all_flags, me, trace,
                             financial_assumptions(ei, fv, beta, verdict), sources(cd, ei, price_src), notes,
                             financial=fv)
    say("Modelling complete")
    return report


def financial_assumptions(ei: EngineInputs, fv: FinancialValuation, beta: Value, verdict: Verdict) -> list[dict]:
    rows = []

    def add(group, name, value, unit, source, editable=None, note=None):
        rows.append({"group": group, "name": name, "value": value, "unit": unit, "source": source,
                     "editable": editable, "note": note})

    add("Cost of equity", "Risk-free rate", ei.risk_free.value, "%", f"{ei.risk_free.source} ({ei.risk_free.period})")
    add("Cost of equity", "Equity risk premium", ei.erp.value, "%", f"{ei.erp.source} ({ei.erp.period})")
    add("Cost of equity", "Beta (levered)", beta.value, "x", beta.source, "beta_choice", beta.note)
    add("Cost of equity", "Country risk premium", ei.crp.value, "%", ei.crp.source, None, ei.crp.note)
    add("Cost of equity", "Cost of equity", fv.cost_of_equity.value, "%",
        fv.cost_of_equity.formula or fv.cost_of_equity.source, "cost_of_equity")
    for a in fv.assumptions:
        add("Valuation", a["name"], a["value"], "%" if a["unit"] == RATIO else "x", a["basis"], a.get("editable"))
    for k, wt in verdict.weights_used.items():
        add("Blend", f"Weight: {method_label(k, fv.toolkit)}", wt, "%",
            "toolkit default, rescaled when a method is missing", "blend_weights")
    return rows


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
