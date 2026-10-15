"""Full report layout (PROMPT.md section 6, corporate companies). Every number is traceable on hover."""
from __future__ import annotations

import plotly.graph_objects as go
import streamlit as st

from data_desk.standardise import DERIVED_LABELS
from data_desk.tags import LINES
from engine.analysis import METRIC_SECTION
from engine.rubric import LABELS, WEIGHTS
from engine.values import MULTIPLE, PER_SHARE, RATIO, Value
from ui.format import (CSS, FLAG_ICON, calc_value, fmt_value, millions, money, mult, pct, plain_table,
                       trace_text, traced_table)

NAMES = {**{k: v.label for k, v in LINES.items()}, **DERIVED_LABELS}
IS_LINES = ["revenue", "cost_of_revenue", "gross_profit", "rnd", "sga", "operating_income", "interest_expense",
            "pretax_income", "income_tax", "net_income_attributable", "ebitda", "sbc", "eps_diluted",
            "shares_diluted_weighted", "non_operating_and_tax_gap"]
BS_LINES = ["cash", "short_term_investments", "receivables", "inventory", "current_assets", "ppe_net", "goodwill",
            "intangibles", "total_assets", "accounts_payable", "current_liabilities", "total_debt",
            "lease_liabilities", "debt_for_valuation", "total_liabilities", "minority_interest", "parent_equity",
            "total_equity", "net_debt"]
CF_LINES = ["cfo", "capex", "capitalised_software_and_intangibles", "fcf", "fcf_after_sbc", "d_and_a",
            "acquisitions", "buybacks", "dividends_paid", "cfi", "cff", "change_in_cash"]
SECTION_TITLES = {"growth": "Growth", "profitability": "Profitability", "returns": "Returns", "quality":
                  "Quality of earnings", "working_capital": "Working capital", "balance_sheet": "Balance sheet",
                  "capital_allocation": "Capital allocation", "track_record": "Management track record"}


def html(s: str) -> None:
    st.markdown(s, unsafe_allow_html=True)


def _metric(label: str, v: Value | None, text: str | None = None, delta: str | None = None) -> None:
    st.metric(label, text if text is not None else fmt_value(v), delta=delta, help=trace_text(v) if v else None,
              delta_color="off")


def statement_table(h, lines: list[str], main_only: bool = True) -> str:
    labels = [p.label for p in h.periods]
    cols = labels[-4:] if main_only else labels
    rows = [(NAMES.get(line, line), [h.get(line, p) for p in cols]) for line in lines
            if any(h.get(line, p) is not None and h.get(line, p).value is not None for p in cols)]
    return traced_table(rows, cols)


# --- 0. verdict card -------------------------------------------------------------------------------------------
def verdict_card(rep) -> None:
    m, cd = rep.model, rep.company
    vd, v = m.verdict, m.valuation
    st.subheader(f"{cd.profile.name} ({cd.profile.ticker}) · {cd.profile.exchange}")
    price = m.inputs.price
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        _metric("Share price", price, money(price.value))
        st.caption(f"{price.source} · {price.period}")
    with c2:
        _metric("Fair value", m.trace.get("fair_value"), money(vd.fair_value),
                delta=None if vd.gap is None else f"{vd.gap:+.1%} vs price")
    with c3:
        colour = {"Undervalued": "#1a7f37", "Overvalued": "#cf222e"}.get(vd.verdict, "#9a6700")
        html(f"<div class='vt-muted'>Verdict</div><div class='vt-verdict' style='color:{colour}'>{vd.verdict}</div>"
             f"<div class='vt-muted'>Confidence: <b>{vd.confidence}</b></div>")
    with c4:
        if rep.md:
            html(f"<div class='vt-muted'>MD rating</div><div class='vt-verdict'>{rep.md.rating}</div>"
                 f"<div class='vt-muted'>Conviction: <b>{rep.md.conviction}</b></div>")
        else:
            html("<div class='vt-muted'>MD rating</div><div class='vt-verdict'>–</div>"
                 "<div class='vt-muted'>AI desks did not run</div>")
    if vd.confidence == "Low":
        st.warning("Low confidence: " + "; ".join(vd.confidence_reasons))
    c1, c2, c3 = st.columns(3)
    if len(v.scenarios) == 3:
        b, base, bu = (v.per_us_share(s.value_per_share) for s in v.scenarios)
        c1.markdown(f"**Bear / base / bull (DCF):** {money(b)} / {money(base)} / {money(bu)}")
    t = m.analyst_targets
    c2.markdown(f"**Analyst target:** {money(t.get('median') or t.get('consensus'))} "
                f"(range {money(t.get('low'))}–{money(t.get('high'))})" if t else
                "**Analyst target:** not available (FMP free plan)")
    c3.markdown(f"**Stage:** {v.classification.stage_label} · **Toolkit:** {v.classification.toolkit}")
    if rep.md and rep.md.view.get("reasoning_lines"):
        for line in rep.md.view["reasoning_lines"][:4]:
            st.markdown(f"- {line}")
    key = [f for f in m.flags if f.level in ("hard_stop", "red", "amber")][:5]
    if key:
        st.markdown("**Key flags:** " + " · ".join(f"{FLAG_ICON[f.level]} {f.title}" for f in key))
    st.caption(f"Report {rep.report_id} · created {rep.created_at} UTC · AI cost ${rep.ai_cost:.3f}")


# --- 1. investment view ---------------------------------------------------------------------------------------
def investment_view(rep) -> None:
    md = rep.md
    if not md:
        st.info("The MD did not run for this report (AI desks off, or the AI cost cap was reached).")
        return
    view = md.view
    st.markdown(f"**Thesis.** {view.get('thesis', '')}")
    rows = [[LABELS[s.criterion], f"{WEIGHTS[s.criterion]:.0%}", str(s.score), s.by, s.evidence] for s in md.scores]
    html(plain_table(rows, ["Criterion", "Weight", "Score (1-5)", "Scored by", "Evidence"]))
    st.markdown(f"Weighted score **{md.weighted_score:.2f}** → code rating **{md.code_rating}**"
                + (f"; MD moved it to **{md.rating}**: {view.get('notch_reason')}" if md.rating != md.code_rating else ""))
    if md.conflict:
        st.warning(f"Rating and valuation verdict point in different directions. MD's explanation: "
                   f"{view.get('rating_vs_verdict_explanation', '')}")
    bvb = view.get("bull_vs_bear", {})
    st.markdown(f"**Bull vs bear.** The MD sides with the **{bvb.get('side', '–')}** case: {bvb.get('why', '')}")
    st.markdown(f"**Response to the bear case.** {view.get('bear_case_response', '')}")
    if rep.md.rating in ("Sell", "Strong Sell"):
        st.markdown(f"**Response to the bull case.** {view.get('bull_case_response', '')}")
    st.markdown("**What has to be true**")
    for x in view.get("what_has_to_be_true", []):
        st.markdown(f"- {x}")
    if view.get("catalysts"):
        html(plain_table([[c["event"], c["date"], c["why"]] for c in view["catalysts"]], ["Catalyst", "Date", "Why"]))
    st.markdown("**What would change our view**")
    for x in view.get("what_would_change_view", []):
        st.markdown(f"- {x}")


# --- 2. business overview ---------------------------------------------------------------------------------------
def business(rep) -> None:
    r = rep.research
    if not r or not r.data:
        st.info("The research desk did not run, so the business overview is not available.")
        return
    d = r.data
    st.markdown(d.get("business_summary", ""))
    if d.get("business_quote"):
        st.caption(f"“{d['business_quote']}” — {r.source}")
    if d.get("segments"):
        st.markdown("**Segments** (latest fiscal year, as reported)")
        html(plain_table([[s["name"], millions(s.get("revenue_millions")), millions(s.get("profit_millions")),
                           s.get("profit_metric", ""), s.get("fiscal_year", "")] for s in d["segments"]],
                         ["Segment", "Revenue (m)", "Profit (m)", "Profit measure", "Year"]))
    if d.get("geographic_mix"):
        st.markdown("**Geographic mix**")
        html(plain_table([[g["region"], millions(g.get("revenue_millions")),
                           "–" if g.get("share_of_revenue_pct") is None else f"{g['share_of_revenue_pct']:.1f}%"]
                          for g in d["geographic_mix"]], ["Region", "Revenue (m)", "Share"]))
    if d.get("kpis"):
        st.markdown("**Operating KPIs**")
        html(plain_table([[k["name"], k["value_text"], k["period"]] for k in d["kpis"]], ["KPI", "Value", "Period"]))
    if r.dropped:
        with st.expander(f"{len(r.dropped)} research items dropped because they could not be verified in the filing"):
            for x in r.dropped:
                st.markdown(f"- {x}")
    st.caption(f"Source: {r.source}. Sections read: " + ", ".join(f"{k} ({v:,} chars)" for k, v in r.sections_found.items()))


# --- 3 / 4. historicals and analysis ------------------------------------------------------------------------------
def historicals(rep) -> None:
    h = rep.company.historicals
    st.caption(f"{h.currency} millions (hover any number for its filing, XBRL tag and fetch time). "
               f"Reports under {h.taxonomy}.")
    for title, lines in (("Income statement", IS_LINES), ("Balance sheet", BS_LINES), ("Cash flow", CF_LINES)):
        st.markdown(f"**{title}**")
        html(statement_table(h, lines))
    with st.expander("All years"):
        for title, lines in (("Income statement", IS_LINES), ("Balance sheet", BS_LINES), ("Cash flow", CF_LINES)):
            st.markdown(f"**{title}**")
            html(statement_table(h, lines, main_only=False))
    for n in h.notes:
        st.caption(n)


def analysis(rep) -> None:
    a, h = rep.company.analysis, rep.company.historicals
    cols = [p.label for p in h.periods][-4:]
    for section, title in SECTION_TITLES.items():
        st.markdown(f"**{title}**")
        names = [m for m, s in METRIC_SECTION.items() if s == section and m in a.metrics]
        if names:
            fmt = (lambda v: mult(v.value) if v.unit == MULTIPLE else (pct(v.value) if v.unit == RATIO else None))
            html(traced_table([(m.replace("_", " ").capitalize(), [a.metrics[m].get(p) for p in cols]) for m in names],
                              cols, formatter=fmt))
        if section == "growth" and a.cagr:
            st.caption(" · ".join(f"{k.replace('_', ' ')}: {pct(v.value)}" for k, v in a.cagr.items()))
        if section == "balance_sheet" and a.debt_maturity:
            html(traced_table([("Debt maturing", [v for _, v in a.debt_maturity])], [n for n, _ in a.debt_maturity]))
        if section == "track_record":
            tr = a.track_record
            if tr.get("quarters"):
                st.markdown(f"Beat EPS consensus in {tr['eps_beats']} of the last {tr['quarters']} quarters "
                            f"(average surprise {pct(tr.get('average_surprise'))}). Guidance record: see research desk.")
            else:
                st.caption("Earnings beat/miss history not available.")
        for line in a.commentary.get(section, []):
            st.markdown(f"- {line}")
    st.caption("Beneish M-score and Altman Z-score arrive in Release 2.")


def benchmarking(rep) -> None:
    c = rep.model.comps
    if not c:
        st.info("No usable peers, so benchmarking is not available.")
        return
    rows = [[b["label"], pct(b["company"]) if "debt" not in b["label"] else mult(b["company"]),
             pct(b["peer_median"]) if "debt" not in b["label"] else mult(b["peer_median"]),
             "–" if b["percentile"] is None else f"{b['percentile']:.0%}", str(b["peers"])]
            for b in c.benchmarks.values()]
    html(plain_table(rows, ["Metric", "Company", "Peer median", "Percentile (100% = best)", "Peers"]))
    st.caption("Peers: " + ", ".join(f"{p.ticker} ({p.name})" for p in c.peers))


# --- 6 / 7. stage, forecast -----------------------------------------------------------------------------------------
def stage(rep) -> None:
    v = rep.model.valuation
    c = v.classification
    st.markdown(f"**{c.stage_label}.** {c.stage_reason}." + (f" Overridden: {c.override}" if c.override else ""))
    ev = c.evidence
    html(plain_table([[k.replace("_", " "), pct(x) if isinstance(x, float) and abs(x) < 5 else str(x)]
                      for k, x in ev.items()], ["Evidence", "Value"]))
    st.markdown(f"**Toolkit:** {c.toolkit_reason}")
    cyc = v.cycle
    if cyc.get("available"):
        st.markdown(f"**Cycle position.** Current operating margin {pct(cyc['current_margin'])} sits at the "
                    f"{cyc['percentile']:.0%} percentile of the last {cyc['years']} years (range "
                    f"{pct(cyc['min_margin'])} to {pct(cyc['max_margin'])}; mid-cycle {pct(cyc['mid_cycle_margin'])}).")
    if rep.review:
        cj = rep.review.get("cycle_judgement", {})
        st.markdown(f"**Review desk cycle judgement: {cj.get('view', '').replace('_', ' ')}.** {cj.get('evidence', '')}")
    if v.structural_case:
        st.markdown(f"**Structural case** (current margin held): {money(v.per_us_share(v.structural_case.value_per_share))} "
                    f"vs normalised {money(v.per_us_share(v.dcf.value_per_share))} per share.")


def forecast(rep) -> None:
    plan = rep.model.valuation.plan
    rows = []
    for d in plan.drivers.values():
        f = (lambda x: "–" if x is None else f"{x:.2f}x") if d.name == "sales_to_capital" else \
            (lambda x: "–" if x is None else pct(x))
        rows.append([d.label, f(d.history.value if d.history else None), f(d.consensus.value if d.consensus else None),
                     f(d.industry.value if d.industry else None), f(d.chosen.value), d.source, d.confidence])
    html(plain_table(rows, ["Driver", "History", "Consensus", "Industry", "Chosen", "Where it came from", "Confidence"]))
    path_rows = [[d.label] + [(f"{x:.2f}" if d.name == "sales_to_capital" else pct(x)) for x in d.path]
                 for d in plan.drivers.values()]
    html(plain_table(path_rows, ["Driver"] + plan.labels))
    st.markdown(f"Terminal growth **{pct(plan.terminal_growth.value)}** ({plan.terminal_growth.note}); terminal ROIC "
                f"**{pct(plan.terminal_roic.value)}** ({plan.terminal_roic.note}).")
    for n in plan.notes:
        st.caption(n)


def revisions(rep) -> None:
    rows = []
    for days, r in rep.model.revisions.items():
        if not r.get("available"):
            rows.append([f"{days} days", "–", "–", r.get("reason", "")])
            continue
        for fy, ch in r["changes"].items():
            rows.append([f"{days} days", fy, f"revenue {pct(ch['revenue'])} · EPS {pct(ch['eps'])}",
                         f"vs snapshot of {r['snapshot_date']}"])
    html(plain_table(rows, ["Window", "Fiscal year", "Change in consensus", "Note"]))
    st.caption("FMP publishes current consensus only; the tool saves a snapshot on every run, so revisions build up "
               "over time.")


# --- 9-15. valuation ------------------------------------------------------------------------------------------------
def wacc(rep) -> None:
    w, i = rep.model.valuation.wacc, rep.model.inputs
    kd = rep.model.valuation.cost_of_debt_detail
    rows = [("Risk-free rate", [i.risk_free]), ("Equity risk premium", [i.erp]),
            ("Regression beta (reference)", [i.beta_regression]),
            ("Industry unlevered beta", [i.industry.unlevered_beta]), ("D/E (market)", [w.de_ratio]),
            ("Beta used", [w.beta]), ("Country risk premium", [i.crp]), ("Cost of equity", [w.cost_of_equity]),
            ("Pre-tax cost of debt", [kd["pre_tax_cost_of_debt"]]), ("Marginal tax rate", [i.marginal_tax]),
            ("After-tax cost of debt", [w.after_tax_cost_of_debt]), ("Equity weight", [w.weight_equity]),
            ("Debt weight", [w.weight_debt]), ("WACC", [w.wacc])]
    betas = {"Regression beta (reference)", "Industry unlevered beta", "Beta used", "D/E (market)"}
    html(traced_table([(n, [x if x is None else x]) for n, [x] in rows], ["Value"],
                      formatter=lambda v: f"{v.value:.2f}" if v in [r[1][0] for r in rows if r[0] in betas]
                      else pct(v.value, 2)))
    st.caption(f"Synthetic rating: {kd['rating']}. Country risk: {i.crp.note}")


def dcf(rep) -> None:
    v = rep.model.valuation
    d = v.dcf
    if not d:
        st.error("The DCF could not be computed: see flags.")
        return
    rows = [[y.label, millions(y.revenue), pct(y.ebit / y.revenue) if y.revenue else "–", millions(y.ebit),
             millions(y.taxes), millions(y.nopat), millions(y.reinvestment), millions(y.fcf), f"{y.period:.2f}",
             f"{y.discount_factor:.3f}", millions(y.pv)] for y in d.years]
    html(plain_table(rows, ["Year", "Revenue", "Op. margin", "EBIT", "Tax", "NOPAT", "Reinvestment", "FCF",
                            "Period", "DF", "PV"]))
    c1, c2, c3 = st.columns(3)
    c1.markdown(f"Sum of PV of FCF **{millions(d.sum_pv_fcf)}**  \nTerminal value **{millions(d.terminal_value)}** "
                f"(PV **{millions(d.pv_terminal_value)}**, {d.tv_share_of_ev:.0%} of EV)")
    bridge_txt = "  \n".join(f"{name}: {millions(x.value)}" for name, x in v.bridge)
    c2.markdown(f"Enterprise value **{millions(d.enterprise_value)}**  \n{bridge_txt}  \nEquity **{millions(d.equity_value)}**")
    c3.markdown(f"Diluted shares **{v.diluted_shares.value:,.1f}m**  \nValue per share "
                f"**{money(v.per_us_share(d.value_per_share))}**"
                + (f"  \nImplied exit EV/EBIT {mult(d.implied_exit_ebit_multiple)}" if d.implied_exit_ebit_multiple else ""))
    st.caption("SBC is a cash cost (GAAP operating income already expenses it); mid-year discounting; cash generated "
               "after the latest balance sheet is counted; terminal reinvestment = growth / terminal ROIC.")


def sotp(rep) -> None:
    s = rep.model.valuation.sotp
    if not s.applicable:
        st.markdown(f"Not applied: {s.reason}.")
        return
    v = rep.model.valuation
    html(plain_table([[n, millions(ev), how] for n, ev, how in s.segment_values], ["Segment", "EV (m)", "Basis"]))
    st.markdown(f"SOTP EV **{millions(s.enterprise_value)}** → **{money(v.per_us_share(s.value_per_share))}** per "
                f"share ({s.reason}).")


def comps(rep) -> None:
    c = rep.model.comps
    if c:
        rows = [[m.label, str(len(m.peer_values)), mult(m.q1), mult(m.median), mult(m.q3), mult(m.company_value),
                 money(m.implied_price)] for m in c.multiples.values()]
        html(plain_table(rows, ["Multiple", "Peers", "25th", "Median", "75th", "Company", "Implied price"]))
        st.caption("Peer selection: " + " → ".join(c.selection_steps))
        with st.expander("Peer multiples"):
            peer_rows = [[p.ticker, p.name, f"{p.market_cap / 1000:,.1f}bn"] +
                         [mult(p.multiples()[k]) for k in ("pe_forward", "pe_trailing", "ev_sales", "ev_ebitda", "ev_fcf")]
                         for p in c.peers]
            html(plain_table(peer_rows, ["Ticker", "Name", "Mkt cap", "Fwd P/E", "P/E", "EV/Sales", "EV/EBITDA", "EV/FCF"]))
    st.markdown("**Own 5-year range**")
    rows = [[h.label, mult(h.low), mult(h.median), mult(h.high), mult(h.current),
             "–" if h.percentile is None else f"{h.percentile:.0%}", money(h.implied_price)] for h in rep.model.history.values()]
    html(plain_table(rows, ["Multiple", "Low", "Median", "High", "Now", "Position", "Implied at median"]))


def reverse_dcf(rep) -> None:
    r = rep.model.valuation.reverse or {}
    g, m = r.get("growth", {}), r.get("margin", {})
    a = rep.company.analysis
    hist = a.cagr.get("revenue_cagr_3y")
    cons = rep.model.valuation.plan.drivers["revenue_growth"].consensus
    if g.get("solved"):
        st.markdown(f"The price implies revenue growing **{pct(g['implied_cagr'])} a year** for {r['years']} years "
                    f"(base case {pct(r['base_cagr'])}; 3-year history {pct(hist.value) if hist else '–'}; consensus "
                    f"year 1 {pct(cons.value) if cons else '–'}).")
    else:
        st.markdown(f"Growth alone: {g.get('reason', 'not solved')}.")
    if m.get("solved"):
        st.markdown(f"Or, holding growth, a terminal operating margin of **{pct(m['implied_terminal_margin'])}** "
                    f"(base case {pct(m['base_terminal_margin'])}).")
    else:
        st.markdown(f"Margins alone: {m.get('reason', 'not solved')}.")


def scenarios(rep) -> None:
    v = rep.model.valuation
    rows = [[s.scenario.name, f"{s.scenario.probability:.0%}", s.scenario.describe(),
             money(v.per_us_share(s.value_per_share)) if s.result else (s.error or "–")] for s in v.scenarios]
    html(plain_table(rows, ["Scenario", "Probability", "Assumptions", "Value per share"]))
    st.markdown(f"Probability-weighted DCF value: **{money(v.per_us_share(v.scenario_value))}**")
    s1, s2 = v.sensitivity_wacc_growth, v.sensitivity_growth_margin
    if s1:
        st.markdown("**WACC × terminal growth** (value per share)")
        html(plain_table([[pct(g)] + [money(v.per_us_share(x)) for x in row] for g, row in
                          zip(s1["terminal_growth"], s1["value_per_share"])],
                         ["g \\ WACC"] + [pct(w) for w in s1["wacc"]]))
    if s2:
        st.markdown("**Revenue growth × operating margin** (shift in points; value per share)")
        html(plain_table([[f"{gs * 100:+.0f}"] + [money(v.per_us_share(x)) for x in row] for gs, row in
                          zip(s2["growth_shift"], s2["value_per_share"])],
                         ["growth \\ margin"] + [f"{m * 100:+.0f}" for m in s2["margin_shift"]]))


def football(rep) -> None:
    bars = [b for b in rep.model.football if b.low is not None and b.high is not None]
    if not bars:
        st.info("No ranges available.")
        return
    price = rep.model.verdict.price
    fig = go.Figure()
    for b in reversed(bars):
        fig.add_trace(go.Bar(y=[b.method], x=[b.high - b.low], base=[b.low], orientation="h",
                             marker_color="#0969da" if "DCF" in b.method else "#8c959f",
                             hovertemplate=f"{b.method}: {money(b.low)} – {money(b.high)}<extra>{b.note}</extra>",
                             showlegend=False))
    fig.add_vline(x=price, line_color="#cf222e", annotation_text=f"Price {money(price)}")
    if rep.model.verdict.fair_value:
        fig.add_vline(x=rep.model.verdict.fair_value, line_dash="dash", line_color="#1a7f37",
                      annotation_text=f"Fair value {money(rep.model.verdict.fair_value)}", annotation_position="bottom")
    fig.update_layout(height=60 + 34 * len(bars), margin=dict(l=10, r=10, t=30, b=10), plot_bgcolor="white",
                      xaxis_title="US$ per share")
    st.plotly_chart(fig, width="stretch")


# --- 18-22. review, risks, flags, provenance, disclaimer ---------------------------------------------------------------
def review_notes(rep) -> None:
    r = rep.review
    if not r:
        st.info("The review desk did not run for this report.")
        return
    html(plain_table([[c["assumption"], c["severity"], c["challenge"], c["resolution"]] for c in r.get("challenges", [])],
                     ["Assumption", "Severity", "Challenge", "Resolution"]))
    sr = r.get("stage_review", {})
    st.markdown(f"**Stage review:** {'agrees' if sr.get('agree') else 'suggests ' + sr.get('suggested_stage', '')}. "
                f"{sr.get('reason', '')}")
    bc = r.get("bear_case", {})
    st.markdown(f"**Strongest bear case.** {bc.get('thesis', '')}")
    for x in bc.get("points", []):
        st.markdown(f"- {x}")
    if rep.md:
        st.markdown(f"**MD's response.** {rep.md.view.get('bear_case_response', '')}")
    bu = r.get("bull_case", {})
    with st.expander("Strongest bull case"):
        st.markdown(bu.get("thesis", ""))
        for x in bu.get("points", []):
            st.markdown(f"- {x}")
    if r.get("flag_explanations"):
        with st.expander("Flag explanations"):
            for f in r["flag_explanations"]:
                st.markdown(f"- **{f['code']}**: {f['explanation']}")


def risks(rep) -> None:
    items = (rep.md.view.get("key_risks") if rep.md else None) or \
            [{"risk": x["title"], "quote": x["quote"]} for x in (rep.research.data.get("risk_factors", []) if rep.research else [])]
    for x in items:
        st.markdown(f"- **{x['risk']}** — “{x.get('quote', '')}”")
    v = rep.model.valuation
    s1 = v.sensitivity_wacc_growth
    if s1 and v.dcf:
        st.markdown(f"**What would change the verdict (quantified):** a WACC 1 point higher takes the DCF to "
                    f"{money(v.per_us_share(s1['value_per_share'][2][4]))}; 1 point lower to "
                    f"{money(v.per_us_share(s1['value_per_share'][2][0]))}; terminal growth 1 point lower to "
                    f"{money(v.per_us_share(s1['value_per_share'][0][2]))}.")


def flags(rep) -> None:
    for f in rep.model.flags:
        with st.expander(f"{FLAG_ICON[f.level]} {f.title}" + (f" ({f.period})" if f.period else "")):
            st.markdown(f.message)
            if f.numbers:
                st.json({k: v for k, v in f.numbers.items()})


def provenance(rep) -> None:
    rows = [[a["group"], a["name"], fmt_assumption(a), a["source"], "yes" if a["editable"] else "", a.get("note") or ""]
            for a in rep.model.assumptions]
    html(plain_table(rows, ["Group", "Assumption", "Value", "Source", "Editable", "Note"]))
    st.markdown("**Data sources**")
    html(plain_table([[s["source"], s["what"], s.get("detail") or "", s.get("fetched_at") or ""] for s in rep.model.sources],
                     ["Source", "What", "Detail", "Fetched (UTC)"]))
    with st.expander("XBRL tag used for every number"):
        h = rep.company.historicals
        html(plain_table([[r["line"], r["period"], r["tag"], r["filing"] or "", "fallback" if r["fallback"] else ""]
                          for r in h.tag_log], ["Line", "Period", "Tag", "Filing", ""]))
    if rep.guard_log:
        with st.expander(f"Number guard log ({len(rep.guard_log)})"):
            for x in rep.guard_log:
                st.markdown(f"- {x}")


def fmt_assumption(a: dict) -> str:
    x = a["value"]
    if x is None:
        return "–"
    return {"%": pct(x, 2), "x": f"{x:.2f}x", "m": f"{x:,.1f}m"}.get(a["unit"], f"{x:,.2f}")


DISCLAIMER = ("This report is based on assumptions and public data and may contain errors. It is not financial "
              "advice. Figures are computed by code from SEC filings and market data; AI is used only for reading, "
              "judgement and writing, and every number it quotes is checked against the computed results.")


SECTIONS = [
    ("1. Investment view", investment_view), ("2. Business overview", business), ("3. Historicals", historicals),
    ("4. Financial analysis", analysis), ("5. Industry benchmarking", benchmarking),
    ("6. Company stage and forecast approach", stage), ("7. Forecast and assumptions", forecast),
    ("8. Estimate revisions", revisions), ("9. WACC", wacc), ("10. DCF", dcf), ("11. Sum of the parts", sotp),
    ("12. Comps and historical multiples", comps), ("13. Reverse DCF", reverse_dcf),
    ("14. Scenarios and sensitivity", scenarios), ("15. Football field", football),
    ("16. News and impact analysis", lambda rep: st.caption("Arrives in Release 2.")),
    ("17. Ownership and insider activity", lambda rep: st.caption("Arrives in Release 2.")),
    ("18. Review desk notes", review_notes), ("19. Main risks", risks), ("20. Flags", flags),
    ("21. Assumptions table and data provenance", provenance),
]


def render_report(rep) -> None:
    html(CSS)
    if rep.stopped and rep.model is None:
        st.error(rep.stopped)
        return
    if rep.stopped:
        st.warning(rep.stopped)
    verdict_card(rep)
    for title, fn in SECTIONS:
        with st.expander(title, expanded=title.startswith(("1.", "15."))):
            try:
                fn(rep)
            except Exception as exc:  # one broken section must not hide the rest of the report
                st.error(f"This section could not be displayed: {type(exc).__name__}: {exc}")
    st.markdown("### 22. Disclaimer")
    st.caption(DISCLAIMER)


__all__ = ["render_report", "calc_value", "PER_SHARE"]
