"""Full report layout (PROMPT.md section 6, corporate companies). Every number is traceable on hover."""
from __future__ import annotations

import re

import plotly.graph_objects as go
import streamlit as st

from data_desk.standardise import DERIVED_LABELS
from data_desk.tags import LINES
from engine.analysis import METRIC_SECTION
from engine.rubric import LABELS, WEIGHTS
from engine.values import MULTIPLE, PER_SHARE, RATIO
from ui.insights import dividend_view, ep_view, exit_view, monte_carlo_view, regression_view, split_view, tornado_view, walk_view
from ui.format import (calc_value, fmt_value, millions, money, mult, pct, plain_table, trace_text, traced_table,
                       when)
from ui.theme import (ACCENT, CSS, guide, GREEN, ICON, MONO, RATING_COLOUR, RED, TEXT, VERDICT_COLOUR, chip, count, esc,
                      note, plotly_layout)

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


def html_note(text: str) -> None:
    html(note(text))


def html(s: str) -> None:
    st.markdown(s, unsafe_allow_html=True)


def statement_table(h, lines: list[str], main_only: bool = True) -> str:
    labels = [p.label for p in h.periods]
    cols = labels[-4:] if main_only else labels
    rows = [(NAMES.get(line, line), [h.get(line, p) for p in cols]) for line in lines
            if any(h.get(line, p) is not None and h.get(line, p).value is not None for p in cols)]
    return traced_table(rows, cols)


# --- 0. header --------------------------------------------------------------------------------------------------
def t(x) -> str:
    """AI or fetched text inside an HTML block: escaped, and no raw newlines (a blank line would end the block)."""
    return esc(x or "").replace("\n", "<br>")


def _kpi(label: str, value: str, sub: str = "", title: str = "", colour: str | None = None, word: bool = False) -> str:
    style = f" style='color:{colour}'" if colour else ""
    shown = esc(value) if word else count(value)
    return (f"<div class='vt-kpi'><div class='l'>{esc(label)}</div>"
            f"<div class='v{' word' if word else ''}'{style} title='{esc(title)}'>{shown}</div>"
            f"<div class='s' title='{esc(sub)}'>{esc(sub) or '&nbsp;'}</div></div>")


def _range_strip(lo: float, hi: float, label: str, price: float, fv: float | None, base: float | None = None) -> str:
    """The model's value range against the share price and fair value, on one axis. The two marker labels sit on
    the outer side of their marks so they never overlap."""
    pts = [lo, hi, price] + ([fv] if fv else [])
    a, b = min(pts), max(pts)
    pad = (b - a) * 0.06 or abs(b) * 0.05 or 1.0
    a, b = a - pad, b + pad

    def x(v):
        return f"{(v - a) / (b - a) * 100:.2f}%"
    marks = [f"<div class='band' style='left:{x(lo)};width:calc({x(hi)} - {x(lo)})'></div>",
             f"<div class='mark' style='left:{x(price)};background:{TEXT}'></div>"]
    def side(v, outward):  # outward from the other mark, unless that would run off the strip's edge
        pos = (v - a) / (b - a)
        return "l" if outward == "r" and pos > 0.8 else ("r" if outward == "l" and pos < 0.2 else outward)
    side_price = side(price, "l" if (fv is None or price <= fv) else "r")
    marks.append(f"<div class='lab {side_price}' style='left:{x(price)};color:{TEXT}'>Price {esc(money(price))}</div>")
    if fv:
        side_fv = side(fv, "r" if price <= fv else "l")
        marks += [f"<div class='mark fv' style='left:{x(fv)};background:{ACCENT}'></div>",
                  f"<div class='lab {side_fv}' style='left:{x(fv)};color:{ACCENT}'>Fair value {esc(money(fv))}</div>"]
    legend = (f"<span><i style='background:rgba(255,122,26,.22);border:1px solid rgba(255,122,26,.6)'></i>{esc(label)} "
              f"<span class='n'>{esc(money(lo))} – {esc(money(hi))}</span>"
              + (f" (base <span class='n'>{esc(money(base))}</span>)" if base is not None else "") + "</span>")
    return (f"<div class='vt-range' role='img' aria-label='{esc(label)}: {esc(money(lo))} to {esc(money(hi))}; "
            f"price {esc(money(price))}'><div class='track'></div>{''.join(marks)}</div>"
            f"<div class='vt-legend'>{legend}</div>")


def _ring(md) -> str:
    """The MD's rating with the weighted rubric score (1 to 5) as a ring that fills on arrival."""
    if not md:
        return ("<div class='vt-rating'><div><div class='c' style='margin:0 0 .2rem'>MD rating</div>"
                "<div class='w' style='color:var(--vt-faint)'>Not rated</div>"
                "<div class='c'>The AI desks did not run for this report</div></div></div>")
    r, score = 36, md.weighted_score or 0
    length = 2 * 3.14159 * r * max(0.0, min(score / 5, 1))
    colour = RATING_COLOUR.get(md.rating, ACCENT)
    moved = f" · rubric said {md.code_rating}" if md.rating != md.code_rating else ""
    return (f"<div class='vt-rating' title='Weighted rubric score {score:.2f} of 5'><div class='ring'>"
            f"<svg width='84' height='84' viewBox='0 0 84 84'><circle cx='42' cy='42' r='{r}' fill='none' "
            f"stroke='#2a231d' stroke-width='6'/><circle class='arc' cx='42' cy='42' r='{r}' fill='none' "
            f"stroke='{ACCENT}' stroke-width='6' stroke-linecap='round' style='--len:{length:.1f}'/></svg>"
            f"<div class='sc'>{score:.2f}<small>of 5</small></div></div>"
            f"<div><div class='c' style='margin:0 0 .2rem'>MD rating</div><div class='w' style='color:{colour}'>"
            f"{esc(md.rating)}</div><div class='c'>Conviction: {esc(md.conviction)}{esc(moved)}</div></div></div>")


def why_rating(rep) -> None:
    """The reasons behind the rating next to the rubric that produced it."""
    md = rep.md
    if not md:
        return
    lines = md.view.get("reasoning_lines") or []
    reasons = "".join(f"<li>{t(x)}</li>" for x in lines[:4]) or "<li>The MD gave no summary lines.</li>"
    rows = []
    for i, s_ in enumerate(md.scores):
        rows.append(f"<div class='row' title='{esc(s_.evidence)}'><span class='k'>{esc(LABELS[s_.criterion])}"
                    f"<small>{WEIGHTS[s_.criterion]:.0%}</small></span><span class='bar'><i style='width:"
                    f"{s_.score / 5 * 100:.0f}%;animation-delay:{.3 + i * .07:.2f}s'></i></span>"
                    f"<span class='s'>{s_.score}</span></div>")
    total = (f"<div class='total'><span>Weighted score → rubric rating</span><span><b>{md.weighted_score:.2f}</b> → "
             f"<b>{esc(md.code_rating)}</b></span></div>")
    html(f"<div class='vt-why'><div class='vt-panel'><h6>Why {esc(md.rating)}</h6><ol class='vt-reasons'>{reasons}"
         f"</ol></div><div class='vt-panel'><h6>How the rating was scored</h6><div class='vt-rubric'>"
         f"{''.join(rows)}{total}</div></div></div>")


def value_strip(m) -> str:
    """The model's value range (DCF bear to bull, or the financial toolkit's methods) against price and fair value."""
    vd, v, fin = m.verdict, m.valuation, getattr(m, "financial", None)
    if fin is not None:
        pts = [x.value for x in fin.methods.values() if x.value is not None]
        return _range_strip(min(pts), max(pts), "Valuation methods", vd.price, vd.fair_value) if pts else ""
    if v is not None and len(v.scenarios) == 3:
        b, base, bu = (v.per_us_share(s_.value_per_share) for s_ in v.scenarios)
        if None not in (b, bu):
            return _range_strip(min(b, bu), max(b, bu), "DCF bear to bull", vd.price, vd.fair_value, base)
    return ""


def verdict_card(rep) -> None:
    m, cd = rep.model, rep.company
    vd, v = m.verdict, m.valuation
    p = cd.profile
    fin = getattr(m, "financial", None)
    price = m.inputs.price
    stage = fin.toolkit.capitalize() if fin is not None else v.classification.stage_label
    tags = [p.exchange, cd.historicals.currency + " reporting" if cd.historicals.currency != "USD" else "USD", stage,
            p.sic_description]
    ident = (f"<div><div class='vt-ticker'>{esc(p.ticker)}</div><div class='vt-name'>{esc(p.name)}</div>"
             f"<div class='vt-tags'>" + "".join(f"<span class='vt-tag'>{esc(x)}</span>" for x in tags if x)
             + "</div></div>")

    imp = getattr(rep, "impact", None)
    fv_sub = (f"News-adjusted {money(imp.adjusted_fair_value)}" if imp is not None and not imp.error
              and imp.adjusted is not None else "Blend of the valuation methods")
    gap_col = None if vd.gap is None else (GREEN if vd.gap > 0 else RED)
    kpis = [
        _kpi("Share price", money(price.value), f"{price.source} · {when(price.period)[:11].strip(', ')}", trace_text(price)),
        _kpi("Fair value", money(vd.fair_value), fv_sub, trace_text(m.trace.get("fair_value")), ACCENT),
        _kpi("Upside", "–" if vd.gap is None else f"{vd.gap:+.1%}", "fair value vs price", colour=gap_col),
        _kpi("Verdict", vd.verdict or "–", f"Confidence: {vd.confidence or '–'}",
             "; ".join(vd.confidence_reasons), VERDICT_COLOUR.get(vd.verdict), word=True),
    ]
    strip = value_strip(m)

    tg = m.analyst_targets
    stats = []
    if tg:
        stats.append(f"Analyst target <span class='n'>{esc(money(tg.get('median') or tg.get('consensus')))}</span> "
                     f"<span class='n' style='color:var(--vt-muted)'>({esc(money(tg.get('low')))}–{esc(money(tg.get('high')))})</span>")
    else:
        stats.append("Analyst target: not available (FMP free plan)")
    if fin is not None:
        stats.append(f"Cost of equity <span class='n'>{pct(fin.cost_of_equity.value)}</span>")
        stats.append(f"Long-run growth <span class='n'>{pct(fin.growth.value)}</span>")
    else:
        stats.append(f"WACC <span class='n'>{pct(v.wacc.wacc.value)}</span>")
        stats.append(f"Toolkit <b>{esc(v.classification.toolkit)}</b>")
    stats.append(f"Report <span class='n'>{esc(when(rep.created_at))}</span>")
    stats.append(f"AI cost <span class='n'>{esc(money(rep.ai_cost, 3))}</span>")

    key = [f for f in m.flags if f.level in ("hard_stop", "red", "amber")]
    chips = "".join(chip(f.level, f.title, f.message) for f in key[:6])
    if len(key) > 6:
        chips += f"<span class='vt-chip info'>+{len(key) - 6} more in Review &amp; flags</span>"
    html(f"<div class='vt-head'><div class='top'>{ident}{_ring(rep.md)}</div><div class='vt-kpis'>{''.join(kpis)}</div>"
         f"{strip}<div class='vt-stats'>{''.join(f'<span>{x}</span>' for x in stats)}</div>"
         + (f"<div class='vt-chips'>{chips}</div>" if chips else "") + "</div>")
    if vd.confidence == "Low":
        html(f"<div class='vt-note warn'><b>Low confidence.</b> {esc('; '.join(vd.confidence_reasons))}.</div>")
    why_rating(rep)


# --- 1. investment view ---------------------------------------------------------------------------------------
def _checks(items: list, icon: str = "check") -> str:
    return "<ul class='vt-checks'>" + "".join(f"<li>{ICON[icon]}{t(x)}</li>" for x in items) + "</ul>"


def investment_view(rep) -> None:
    md = rep.md
    if not md:
        html_note("The MD did not run for this report (AI desks off, or the AI cost cap was reached).")
        return
    view = md.view
    html(f"<div class='vt-thesis'>{t(view.get('thesis', ''))}</div>")
    if md.conflict:
        st.warning(f"Rating and valuation verdict point in different directions. MD's explanation: "
                   f"{view.get('rating_vs_verdict_explanation', '')}")
    if getattr(md, "gate_note", ""):
        html(f"<div class='vt-note'>{esc(md.gate_note)}. The rating follows the valuation: a strong business at "
             "too high a price is a Hold, not a Buy.</div>")
    elif md.rating != md.code_rating:
        html(f"<div class='vt-note'>The rubric gives <b>{esc(md.code_rating)}</b>; the MD moved it to "
             f"<b>{esc(md.rating)}</b>: {t(view.get('notch_reason'))}</div>")

    bvb = view.get("bull_vs_bear", {})
    side = (bvb.get("side") or "").lower()
    rv = rep.review or {}
    cases = {"bull": rv.get("bull_case", {}).get("thesis"), "bear": rv.get("bear_case", {}).get("thesis")}
    html("<div class='vt-sub'>Bull vs bear</div><div class='vt-duel'>" + "".join(
        f"<div class='side{' won' if side == k else ''}'><h6>{k.capitalize()} case"
        + ("<span class='badge'>MD sides here</span>" if side == k else "") + "</h6><p>"
        + (t(cases[k]) if cases[k] else "The review desk did not write this case.") + "</p></div>"
        for k in ("bull", "bear")) + "</div>")
    st.markdown(f"**Why the MD sides with the {bvb.get('side', '–')} case.** {bvb.get('why', '')}")
    st.markdown(f"**Response to the bear case.** {view.get('bear_case_response', '')}")
    if rep.md.rating in ("Sell", "Strong Sell"):
        st.markdown(f"**Response to the bull case.** {view.get('bull_case_response', '')}")
    if view.get("what_has_to_be_true"):
        html("<div class='vt-sub'>What has to be true</div>" + _checks(view["what_has_to_be_true"]))
    if view.get("catalysts"):
        html("<div class='vt-sub'>Catalysts</div><div class='vt-timeline'>" + "".join(
            f"<div class='ev'><b>{t(c.get('event'))}</b><span class='d'>{t(c.get('date'))}</span>"
            f"<p>{t(c.get('why'))}</p></div>" for c in view["catalysts"]) + "</div>")
    if view.get("what_would_change_view"):
        html("<div class='vt-sub'>What would change our view</div>" + _checks(view["what_would_change_view"], "arrow"))
    with st.expander("Rubric evidence: every criterion, its score and who scored it"):
        rows = [[LABELS[s.criterion], f"{WEIGHTS[s.criterion]:.0%}", str(s.score), s.by, s.evidence] for s in md.scores]
        html(plain_table(rows, ["Criterion", "Weight", "Score (1-5)", "Scored by", "Evidence"]))


# --- 2. business overview ---------------------------------------------------------------------------------------
def filled_columns(rows: list[list], headers: list[str]) -> tuple[list[list], list[str]]:
    """Drop columns the filing left empty in every row (e.g. segment revenue when only profit is disclosed)."""
    keep = [i for i in range(len(headers)) if i == 0 or any(str(r[i]) not in ("", "–") for r in rows)]
    return [[r[i] for i in keep] for r in rows], [headers[i] for i in keep]


def business(rep) -> None:
    r = rep.research
    if not r or not r.data:
        html_note("The research desk did not run, so the business overview is not available.")
        return
    d = r.data
    st.markdown(d.get("business_summary", ""))
    if d.get("business_quote"):
        st.caption(f"“{d['business_quote']}” — {r.source}")
    if d.get("segments"):
        st.markdown("**Segments** (latest fiscal year, as reported)")
        html(plain_table(*filled_columns([[s["name"], millions(s.get("revenue_millions")),
                                            millions(s.get("profit_millions")), s.get("profit_metric", ""),
                                            s.get("fiscal_year", "")] for s in d["segments"]],
                                          ["Segment", "Revenue (m)", "Profit (m)", "Profit measure", "Year"])))
    if d.get("geographic_mix"):
        st.markdown("**Geographic mix**")
        html(plain_table(*filled_columns([[g["region"], millions(g.get("revenue_millions")),
                                            "–" if g.get("share_of_revenue_pct") is None
                                            else f"{g['share_of_revenue_pct']:.1f}%"] for g in d["geographic_mix"]],
                                          ["Region", "Revenue (m)", "Share"])))
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
    fin = getattr(rep.model, "financial", None) if rep.model else None
    if fin is not None:
        from ui.financial import FS_LINES
        st.markdown(f"**Key lines ({fin.toolkit})**")
        html(statement_table(h, FS_LINES[fin.toolkit]))
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
    forensic_block(with_piotroski(getattr(rep, "forensic", None), rep))


def benchmarking(rep) -> None:
    c = rep.model.comps
    if not c:
        html_note("No usable peers, so benchmarking is not available.")
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
    html(guide("The stage decides how the forecast behaves: how fast growth fades to the industry rate, whether "
               "margins move towards a target, and which methods are weighted. It is set by code from the evidence "
               "below; the cycle check asks whether today's margin is a peak that should not be carried forward."))
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
    html(guide("Each driver shows the company's history, the analysts' consensus and the industry figure next to the "
               "value chosen, and says which one was used and why. The second table is the year-by-year path the "
               "DCF below uses."))
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
    if None not in (w.weight_equity, w.cost_of_equity, w.weight_debt, w.after_tax_cost_of_debt, w.wacc):
        html(guide(f"WACC is the return investors require, used to discount future cash flows: equity weight x cost of "
                   f"equity + debt weight x after-tax cost of debt = {pct(w.weight_equity.value)} x "
                   f"{pct(w.cost_of_equity.value, 2)} + {pct(w.weight_debt.value)} x "
                   f"{pct(w.after_tax_cost_of_debt.value, 2)} = {pct(w.wacc.value, 2)}. Cost of equity = risk-free "
                   "rate + beta x equity risk premium + country risk. Hover a value for its source and date.",
                   "Why this number"))
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
    html(guide("Each year: revenue x operating margin = EBIT; less tax = NOPAT; less the reinvestment needed to grow "
               "= free cash flow (FCF), discounted at WACC to today (PV). The terminal value covers every year after "
               "the last. Enterprise value less debt, plus cash and investments, gives equity; divided by diluted "
               "shares, the value per share.", "Why this number"))
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
    exit_view(rep)
    split_view(rep)
    ep_view(rep)
    dividend_view(rep)


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
        html(guide("Implied price = the peers' median multiple applied to the company's own figure (sales, EBITDA, "
                   "earnings or free cash flow), then bridged from enterprise value to equity per share. The 25th "
                   "and 75th percentiles show how far the peers spread. Below the table, the same multiples are "
                   "adjusted for how profitable or fast-growing the company is."))
        rows = [[m.label, str(len(m.peer_values)), mult(m.q1), mult(m.median), mult(m.q3), mult(m.company_value),
                 money(m.implied_price)] for m in c.multiples.values()]
        html(plain_table(rows, ["Multiple", "Peers", "25th", "Median", "75th", "Company", "Implied price"]))
        st.caption("Peer selection: " + " → ".join(c.selection_steps))
        if c.excluded:
            st.caption("Excluded as not meaningful: " + "; ".join(c.excluded))
        with st.expander("Peer multiples"):
            peer_rows = [[p.ticker, p.name, f"{p.market_cap / 1000:,.1f}bn"] +
                         [mult(p.multiples()[k]) for k in ("pe_forward", "pe_trailing", "ev_sales", "ev_ebitda", "ev_fcf")]
                         for p in c.peers]
            html(plain_table(peer_rows, ["Ticker", "Name", "Mkt cap", "Fwd P/E", "P/E", "EV/Sales", "EV/EBITDA", "EV/FCF"]))
        regression_view(rep)
    st.markdown("**Own 5-year range**")
    rows = [[h.label, mult(h.low), mult(h.median), mult(h.high), mult(h.current),
             "–" if h.percentile is None else f"{h.percentile:.0%}", money(h.implied_price)] for h in rep.model.history.values()]
    html(plain_table(rows, ["Multiple", "Low", "Median", "High", "Now", "Position", "Implied at median"]))


def reverse_dcf(rep) -> None:
    r = rep.model.valuation.reverse or {}
    g, m = r.get("growth", {}), r.get("margin", {})
    html(guide("Instead of asking what the company is worth, this asks what the share price already assumes: the "
               "growth or margin that would make our DCF equal the price, holding everything else. Compare it with "
               "the history and consensus in brackets."))
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
    walk_view(rep)
    st.caption("Analysts' price targets usually rest on an earnings multiple the stock has traded on, which assumes "
               "the market's pricing is right; the DCF tests it at a required return built from the risk-free rate "
               f"({pct(rep.model.inputs.risk_free.value)}), beta and the equity risk premium.")


def scenarios(rep) -> None:
    v = rep.model.valuation
    html(guide("Bear and bull move four inputs together; the grids move two at a time and keep the rest at the base "
               "case (the middle cell equals our DCF). Read across a row to see how much one input matters."))
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
    tornado_view(rep)
    monte_carlo_view(rep)


def _family(method: str) -> str:
    m = method.lower()
    if m.startswith(("52-week", "analyst")):
        return "market"
    if m.startswith(("comps", "peer", "own history")):
        return "multiples"
    return "intrinsic"


FAMILY_COLOUR = {"intrinsic": "rgba(255,122,26,.85)", "multiples": "rgba(196,180,156,.5)", "market": "rgba(133,123,110,.32)"}


def football(rep) -> None:
    bars = [b for b in rep.model.football if b.low is not None and b.high is not None]
    if not bars:
        html_note("No valuation ranges are available for this report.")
        return
    price, fv = rep.model.verdict.price, rep.model.verdict.fair_value
    html(guide("Each bar is the range one method gives (low to high case). The white line is the share price, the "
               "dotted orange line the blended fair value. Where most orange bars sit left of the price, the "
               "fundamentals do not support it; the Valuation tab shows how each bar is built."))
    fig = go.Figure()
    for b in reversed(bars):  # first method at the top
        span = b.high - b.low
        colour = FAMILY_COLOUR[_family(b.method)]
        tip = f"<b>{b.method}</b><br>{money(b.low)} – {money(b.high)}" + (f"<br>{b.note}" if b.note else "")
        if span > 0:
            fig.add_trace(go.Bar(y=[b.method], x=[span], base=[b.low], orientation="h", marker_color=colour,
                                 marker_line_width=0, width=0.55, hovertemplate=tip + "<extra></extra>"))
        else:  # a single point estimate
            fig.add_trace(go.Scatter(y=[b.method], x=[b.low], mode="markers", hovertemplate=tip + "<extra></extra>",
                                     marker=dict(symbol="line-ns", size=16, line=dict(width=3, color=colour))))
    fig.add_vline(x=price, line_color=TEXT, line_width=1.5)
    fig.add_annotation(x=price, y=1, yref="paper", yanchor="bottom", text=f"Price {money(price)}", showarrow=False,
                       font=dict(family=MONO, size=11, color=TEXT), xanchor="right" if (fv or 0) > price else "left",
                       xshift=-6 if (fv or 0) > price else 6)
    if fv:
        fig.add_vline(x=fv, line_color=ACCENT, line_width=1.5, line_dash="dot")
        fig.add_annotation(x=fv, y=1, yref="paper", yanchor="bottom", text=f"Fair value {money(fv)}", showarrow=False,
                           font=dict(family=MONO, size=11, color=ACCENT), xanchor="left" if fv > price else "right",
                           xshift=6 if fv > price else -6)
    ref = max(x for x in (price, fv or 0) if x)
    cap = 3 * ref
    for b in bars:
        if b.high > cap:  # an extreme range (e.g. a peer P/E near zero earnings): cut at 3x and say where it ends
            fig.add_annotation(x=cap, y=b.method, text=f"→ {money(b.high, 0)}", showarrow=False, xanchor="right",
                               font=dict(family=MONO, size=10, color=TEXT))
    lo_x = min(min(b.low for b in bars), price, fv or price)
    fig.update_layout(**plotly_layout(height=90 + 38 * len(bars), bargap=0.4, margin=dict(l=10, r=20, t=34, b=46),
                                      xaxis=dict(title=dict(text="US$ per share"), tickprefix="$", side="bottom",
                                                 range=[max(0.0, lo_x * 0.85), min(cap, max(b.high for b in bars) * 1.05)]),
                                      yaxis=dict(automargin=True)))
    st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})
    st.caption("Orange: intrinsic methods (DCF, residual income, dividend model, NAV). Grey: peer and historical "
               "multiples. Faint: analyst targets and the 52-week range, for reference. Hover a bar for its source.")


# --- 18-22. review, risks, flags, provenance, disclaimer ---------------------------------------------------------------
def review_notes(rep) -> None:
    r = rep.review
    if not r:
        html_note("The review desk did not run for this report.")
        return
    html(plain_table([[c["assumption"] or "(removed: a number failed the check; see Desk log)", c["severity"], c["challenge"], c["resolution"]] for c in r.get("challenges", [])],
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
    s1 = v.sensitivity_wacc_growth if v is not None else None
    if s1 and v.dcf:
        st.markdown(f"**What would change the verdict (quantified):** a WACC 1 point higher takes the DCF to "
                    f"{money(v.per_us_share(s1['value_per_share'][2][4]))}; 1 point lower to "
                    f"{money(v.per_us_share(s1['value_per_share'][2][0]))}; terminal growth 1 point lower to "
                    f"{money(v.per_us_share(s1['value_per_share'][0][2]))}.")


def flags(rep) -> None:
    if rep.model.flags:
        html(guide("Hard stop: the data failed a check and the stock is not valued. Red: a line that does not add up "
                   "or a serious risk. Amber: worth reading before trusting the number (e.g. EDGAR and FMP disagree by "
                   "more than 2%, both figures shown). Info: context. Open a flag for the figures behind it."))
    for f in rep.model.flags:
        tag = {"hard_stop": ":red[**Hard stop**]", "red": ":red[**Red**]", "amber": ":orange[**Amber**]"}.get(f.level, ":gray[Info]")
        with st.expander(f"{tag} · {f.title}" + (f" ({f.period})" if f.period else "")):
            st.markdown(f.message)
            if f.numbers:
                st.json({k: v for k, v in f.numbers.items()})


def provenance(rep) -> None:
    rows = [[a["group"], a["name"], fmt_assumption(a), a["source"], "yes" if a["editable"] else "", a.get("note") or ""]
            for a in rep.model.assumptions]
    html(plain_table(rows, ["Group", "Assumption", "Value", "Source", "Editable", "Note"]))
    st.markdown("**Data sources**")
    html(plain_table([[s["source"], s["what"], s.get("detail") or "", when(s["fetched_at"]) if s.get("fetched_at") else ""]
                      for s in rep.model.sources],
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
    ("16. News and impact analysis", lambda rep: news_section(rep)),
    ("17. Ownership and insider activity", lambda rep: ownership_section(rep)),
    ("18. Review desk notes", review_notes), ("19. Main risks", risks), ("20. Flags", flags),
    ("21. Assumptions table and data provenance", provenance),
]


def financial_sections() -> list:
    """Banks, insurers, REITs: the same report with the analysis and valuation sections changed (no DCF)."""
    from ui.financial import SECTIONS_FIN
    shared = dict(SECTIONS)
    out = [s for s in SECTIONS if s[0].startswith(("1.", "2.", "3."))] + SECTIONS_FIN[:4]
    out.append(("8. Estimate revisions", shared["8. Estimate revisions"]))
    out.append(SECTIONS_FIN[4])
    n = 10
    for title in ("15. Football field", "16. News and impact analysis", "17. Ownership and insider activity",
                  "18. Review desk notes", "19. Main risks", "20. Flags", "21. Assumptions table and data provenance"):
        out.append((f"{n}. {title.split('. ', 1)[1]}", shared[title]))
        n += 1
    return out


def md_text(x: str) -> str:
    """Fetched text shown as plain words: no LaTeX from "$5bn ... $4bn", no stray links or emphasis."""
    return re.sub(r"([\\`*_\[\]<>#|$~])", r"\\\1", x or "")


QUALITY_BADGE = {"Trusted": "🟢 Trusted", "Established": "🔵 Established", "Unverified": "🟠 Unverified"}


def with_piotroski(fs, rep):
    """Reports saved before the F-score was added get it computed now from their stored statements (pure code)."""
    if not fs or fs.get("piotroski") or rep.company is None:
        return fs
    from engine.forensic import _consecutive, piotroski
    h = rep.company.historicals
    labels = list(h.fy_labels)
    try:
        return {**fs, "piotroski": [piotroski(h, rep.company.profile.sic, y, p)
                                    for p, y in zip(labels, labels[1:]) if _consecutive(p, y)]}
    except Exception:  # a cross-check: never stop the page
        return fs


def forensic_block(fs) -> None:
    st.markdown("**Forensic scores** (code, from reported statement lines)")
    if not fs or not (fs.get("beneish") or fs.get("altman")):
        st.caption("Forensic scores not available for this report"
                   + (f": {fs['error']}" if fs and fs.get("error") else "."))
        return
    rows = []
    for s_ in fs.get("beneish", [])[-4:] + fs.get("altman", [])[-4:] + fs.get("piotroski", [])[-4:]:
        f_score = s_.name.startswith("Piotroski")
        failed = [k for k, v in s_.components.items() if not v]
        rows.append({"Score": s_.name, "Year": s_.period,
                     "Value": "n/a" if s_.value is None else f"{s_.value:.0f}" if f_score else f"{s_.value:.2f}",
                     "Reading": s_.reading,
                     "Components": ("failed: " + ", ".join(failed) if failed else "every scored test passed")
                     if f_score and s_.components else ", ".join(f"{k} {v:.2f}" for k, v in s_.components.items())})
    st.dataframe(rows, hide_index=True, width="stretch")
    latest = [x for x in (fs.get("beneish") or [])[-1:] + (fs.get("altman") or [])[-1:]
              + (fs.get("piotroski") or [])[-1:]]
    for x in latest:
        st.caption(f"{x.name} ({x.model}): " + "; ".join(x.notes) if x.notes else f"{x.name}: {x.model}.")
    with st.expander("Forensic score inputs (line, period, value, source)"):
        for x in latest:
            st.markdown(f"**{x.name} {x.period}**")
            st.dataframe([{"Line": i["line"], "Period": i["period"], "Value (US$m)": f"{i['value']:,.1f}",
                           "Source": i["source"]} for i in x.inputs], hide_index=True, width="stretch")


def ownership_section(rep) -> None:
    own = getattr(rep, "ownership", None)
    if own is None:
        st.caption("Ownership data was not gathered for this report.")
        return
    s_ = own.summary()
    st.markdown(f"**Insider activity, last {s_['window_days']} days** (SEC Form 4, as of {own.as_of})")
    c1, c2, c3 = st.columns(3)
    c1.metric("Open-market buys", f"{s_['buys']} ({s_['buyers']} insiders)", help="Form 4 code P")
    c2.metric("Open-market sells", f"{s_['sells']} ({s_['sellers']} insiders)",
              help=f"Form 4 code S; {s_['planned_sells']} under pre-arranged Rule 10b5-1 plans")
    c3.metric("Net (buys − sells), US$m", f"{s_['net_value'] / 1e6:+,.2f}",
              help="Shares × reported price, summed by code")
    st.caption(f"Bought US${s_['buy_value'] / 1e6:,.2f}m; sold US${s_['sell_value'] / 1e6:,.2f}m (shares × "
               "reported price).")
    if s_["sells"]:
        st.caption(f"{s_['planned_sells']} of {s_['sells']} sales were under Rule 10b5-1 plans (scheduled in "
                   "advance, a weaker signal than discretionary sales). Option exercises, grants and tax "
                   "withholding are listed but not counted as buying or selling.")
    if own.trades:
        st.dataframe([{"Date": t.date, "Insider": t.owner, "Role": t.role, "Transaction": t.action,
                       "Shares": f"{t.shares:,.0f}", "Price": money(t.price) if t.price else "",
                       "Value (US$m)": f"{t.value / 1e6:,.2f}" if t.value else "",
                       "10b5-1": "yes" if t.plan_10b5_1 else "", "Filed": t.filed, "Link": t.url}
                      for t in own.trades[:40]], hide_index=True, width="stretch",
                     column_config={"Link": st.column_config.LinkColumn("Form 4", display_text="filing")})
    st.markdown("**Major holders** (5% filers, latest Schedule 13D/13G per filer)")
    if own.holders:
        st.dataframe([{"Holder": h.name, "% of class": "n/a" if h.percent is None else
                       f"{h.percent:g}%" + (" (below 5%: exit or update filing)" if h.percent < 5 else ""),
                       "Shares": "" if h.shares is None else f"{h.shares:,.0f}", "As of": h.event_date,
                       "Class": getattr(h, "security", ""), "Form": h.form, "Filed": h.filed, "Link": h.url}
                      for h in own.holders],
                     hide_index=True, width="stretch",
                     column_config={"Link": st.column_config.LinkColumn("Filing", display_text="filing")})
    else:
        st.caption("No Schedule 13D/13G filings in the SEC's XML format in the last 3 years.")
    if own.institutional:
        st.markdown(f"**Institutional holders** (FMP, from 13F filings for {own.institutional_period})")
        st.dataframe(own.institutional[:15], hide_index=True, width="stretch")
    st.markdown("**Short interest** (FINRA, twice-monthly settlement dates)")
    if own.short:
        st.dataframe([{"Settlement date": r["settlement_date"],
                       "Short shares": "" if r["short_shares"] is None else f"{r['short_shares']:,.0f}",
                       "% of shares outstanding": "n/a" if r["pct_of_shares"] is None else f"{r['pct_of_shares']:.2%}",
                       "Change": "n/a" if r["change_pct"] is None else f"{r['change_pct']:+.1%}",
                       "Days to cover": "" if r["days_to_cover"] is None else f"{r['days_to_cover']:.2f}"}
                      for r in reversed(own.short)], hide_index=True, width="stretch")
        st.caption("% of shares outstanding uses the latest reported share count (code). Days to cover is FINRA's: "
                   "short shares ÷ average daily volume.")
    for n in own.notes:
        st.caption(n)


def _pct(x: float | None) -> str:
    return "n/a" if x is None else f"{x:+.1%}"


def news_meaning(imp) -> None:
    """The MD's 'What the news means': news-adjusted fair value next to the (news-free) base fair value."""
    st.markdown("#### What the news means")
    if imp.error:
        st.warning(f"The impact analysis failed: {imp.error}")
        return
    c1, c2, c3 = st.columns(3)
    c1.metric("Base fair value (news-free)", money(imp.base_fair_value), help="The reproducible valuation; news "
              "never changes it.")
    adj = imp.adjusted_fair_value
    delta = None if adj is None or not imp.base_fair_value else f"{adj / imp.base_fair_value - 1:+.1%} vs base"
    c2.metric("News-adjusted fair value", money(adj), delta=delta,
              help="The base model repriced with every quantified news effect (computed by code).")
    c3.metric("Verdict after news", (imp.adjusted.verdict if imp.adjusted else imp.base_verdict) or "n/a",
              help=f"Base verdict: {imp.base_verdict}")
    v = imp.view
    if v:
        st.markdown(md_text(v.get("what_news_means", "")))
        shift = {"bull": "more likely the bull case", "bear": "more likely the bear case",
                 "neither": "neither scenario more likely"}.get(v.get("scenario_shift"), "")
        st.markdown(f"**Scenarios:** news makes {shift}. {md_text(v.get('scenario_why', ''))}")
        st.markdown(f"**Rating:** {'changed by the news' if v.get('changes_rating') else 'unchanged by the news'}. "
                    f"{md_text(v.get('rating_why', ''))}")
    if imp.benchmarks:
        st.caption("Priced in? uses the abnormal return since each item: the stock vs "
                   + " and ".join(x for x in (imp.benchmarks.get("market"), imp.benchmarks.get("sector")) if x)
                   + " (daily closes), compared with the item's fair value effect as a share of the price.")
    for n in imp.notes:
        st.caption(n)


def impact_block(x) -> None:
    from engine.news_impact import DRIVER_LABEL, UNIT

    lines = [f"**Impact analysis** ({x.duration}) · driver: {DRIVER_LABEL.get(x.driver, x.driver)}"]
    if x.quantified:
        unit = UNIT.get(x.driver, "percentage points")
        eff = f"{money(x.fair_value_effect)} per share on fair value" if x.fair_value_effect is not None else ""
        timed = x.driver in ("revenue_growth", "operating_margin")
        eps = (f", {money(x.eps_effect)} on year-1 operating earnings per share (after tax, before interest)"
               if x.eps_effect is not None and timed else "")
        span = f" for {x.years} year{'s' if x.years != 1 else ''}" if timed else ""
        lines.append(f"Size (code): {x.change:+g} {unit}{span} → {eff}{eps}"
                     + (f". Disclosed sensitivity used: \"{md_text(x.sensitivity_quote)}\"" if x.sensitivity_quote
                        else ""))
    else:
        lines.append(f"Size: qualitative only. {md_text(x.reason)}")
    pr = x.priced
    if pr is not None:
        lines.append(f"Priced in? **{pr.verdict}**: stock {_pct(pr.stock_return)}; abnormal return "
                     f"{_pct(pr.abnormal_vs_market)} vs the S&P 500"
                     + (f", {_pct(pr.abnormal_vs_sector)} vs the sector ETF" if pr.abnormal_vs_sector is not None
                        else "")
                     + (f" ({pr.window})" if pr.window else "")
                     + (f"; estimated effect {_pct(pr.estimated_impact)} of the price" if pr.estimated_impact is not None
                        else "") + (f". {pr.note}" if pr.note and pr.verdict in ("too recent to judge", "no benchmark")
                                   else ""))
    lines.append(f"How it reaches the business: {md_text(x.chain)}")
    lines.append(f"Bull: {md_text(x.bull)}  \nBear: {md_text(x.bear)}  \n"
                 f"More convincing: **{x.more_convincing}**. {md_text(x.why)}")
    if x.watch:
        lines.append("What to watch: " + "; ".join(f"{md_text(w['event'])} ({md_text(w['date'])})" for w in x.watch))
    st.markdown("  \n".join(lines))


def news_section(rep) -> None:
    from desks.news import MAX_AGE_DAYS, TIER_LABEL, TIERS

    exp = getattr(rep, "exposure", None)
    news = getattr(rep, "news", None)
    if exp is not None:
        st.markdown("**Exposure profile** (how outside events reach the business; macro news must hit one of these)")
        st.dataframe([{"Category": e.category, "Channel": e.channel, "Detail": e.detail, "Source": e.source}
                      for e in exp.items], hide_index=True, width="stretch")
        for n in exp.notes:
            st.caption(n)
    if news is None:
        st.caption("The news desk did not run for this report.")
        return
    if news.error:
        st.warning(f"The news desk failed: {news.error}")
        return
    st.markdown(f"**News as of {news.as_of[:16].replace('T', ' ')} UTC**")
    imp = getattr(rep, "impact", None)
    by_item = {id(x.item): x for x in imp.items} if imp else {}
    if imp is not None:
        news_meaning(imp)
    for t in TIERS:
        items = news.tier(t)
        st.markdown(f"##### {TIER_LABEL[t]}")
        if not items:
            st.caption(f"No material news in the last {MAX_AGE_DAYS[t]} days.")
        for i in items:
            url = i.url.replace("(", "%28").replace(")", "%29").replace(" ", "%20")
            st.markdown(f"**[{md_text(i.headline)}]({url})**  \n"
                        f"{TIER_LABEL[i.tier]} · {i.published} · {md_text(i.source)} · "
                        f"{QUALITY_BADGE.get(i.quality, i.quality)}"
                        + (f" · channel: {md_text(i.channel)}" if i.channel else "")
                        + (" · latest earnings release" if i.earnings_release else ""))
            if i.summary:
                st.markdown(md_text(i.summary))
            if i.why_material:
                st.caption(f"Why it matters: {md_text(i.why_material)}")
            st.caption(f"Date verified from: {i.date_basis} ({i.origin})")
            if id(i) in by_item:
                impact_block(by_item[id(i)])
    if any(i.quality == "Unverified" for i in news.items):
        st.caption("Unverified sources can be discussed but never change model numbers unless a Trusted or "
                   "Established source corroborates them.")
    if news.dropped:
        with st.expander(f"{len(news.dropped)} items dropped by the freshness and verification rules"):
            for d in news.dropped:
                st.caption(d)


TABS = {  # section name (without its number) -> tab
    "Investment view": "Overview", "Business overview": "Overview", "Football field": "Overview",
    "Main risks": "Overview",
    "Historicals": "Financials", "Financial analysis": "Financials", "Industry benchmarking": "Financials",
    "Sector metrics": "Financials", "Peer comparison": "Financials",
    "News and impact analysis": "News & ownership", "Ownership and insider activity": "News & ownership",
    "Review desk notes": "Review & flags", "Flags": "Review & flags",
    "Assumptions table and data provenance": "Sources",
}
TAB_ORDER = ["Overview", "Valuation", "Financials", "News & ownership", "Review & flags", "Sources"]
TAB_GUIDE = {  # what each tab holds, in the order you scroll through it
    "Overview": "The MD's investment view and the bull and bear cases, what the company does, the football field (every "
                "valuation method on one chart) and the main risks. Scroll down for each.",
    "Valuation": "How the fair value is built, in order: the company's stage, the forecast and where each driver comes "
                 "from, WACC, the DCF and what the price is paying for, sum of the parts, peer and own-history "
                 "multiples, the reverse DCF with the walk from our value to the share price, then scenarios and the "
                 "Monte Carlo range.",
    "Financials": "Ten years of reported statements (hover any number for its filing, XBRL tag and fetch date), the "
                  "ratios computed from them, and how the company ranks against its industry and its peers.",
    "News & ownership": "Recent dated news, each item's sized effect on fair value and whether the market has already "
                        "priced it in; then insider trades, major holders and short interest.",
    "Review & flags": "An independent reviewer's challenges to the assumptions and the strongest bear and bull cases, "
                      "then every data and valuation flag with what it means for this company.",
    "Sources": "Every assumption with its value and where it comes from, and every data source with the date it was "
               "fetched.",
    "What if": "Move a slider and the DCF reprices instantly, in Python. The presets jump to our base case, to common "
               "sell-side conventions, or to the discount rate the share price implies.",
    "History": "Every dated report on this company: how the fair value and the rating moved against the price, and "
               "what changed between runs.",
}
FINANCIAL_VALUATION_GUIDE = ("How the fair value is built for a bank, insurer or REIT (a DCF does not fit them): the "
                             "sector metrics, the cost of equity, then each valuation method and the blend.")
WEIGHT_NAMES = {"dcf": "DCF", "comps": "peer multiples", "history": "own-history multiples", "sotp": "sum of the parts",
                "justified": "justified price-to-book", "residual_income": "residual income",
                "ddm": "dividend discount", "comps_pb": "peer price-to-book", "comps_pe": "peer P/E",
                "nav": "net asset value", "comps_pffo": "peer P/FFO"}


def start_here(rep) -> None:
    """One line under the header: how the headline numbers relate, and where to find how each is built."""
    vd = rep.model.verdict
    w = getattr(vd, "weights_used", None) or {}

    def name(k: str) -> str:
        return WEIGHT_NAMES.get(k, k.replace("_", " "))
    blend_txt = ", ".join(f"{name(k)} {x:.0%}" for k, x in w.items() if x) if w else ""
    html(guide((f"The fair value blends the methods ({blend_txt}); " if blend_txt else "The fair value blends the "
                "valuation methods; ") + "the verdict compares it with the price; the rating also weighs business "
               "quality and the other criteria scored on the right, and is capped at Hold when the stock looks "
               "overvalued. Hover a figure for its source, or use the tabs below for how each number is built.",
               "Start here"))


def render_report(rep, extra_tabs: list | None = None) -> None:
    """Header, then the numbered sections grouped into tabs (numbers match the PDF). `extra_tabs`: [(name, fn)]."""
    html(CSS)
    if rep.stopped and rep.model is None:
        st.error(rep.stopped)
        return
    if rep.stopped:
        st.warning(rep.stopped)
    verdict_card(rep)
    fin = getattr(rep.model, "financial", None)
    groups: dict[str, list] = {t: [] for t in TAB_ORDER}
    for title, fn in (financial_sections() if fin is not None else SECTIONS):
        groups[TABS.get(title.split(". ", 1)[1], "Valuation")].append((title, fn))
    names = [t for t in TAB_ORDER if groups[t]] + [n for n, _ in (extra_tabs or [])]
    start_here(rep)
    for name, tab in zip(names, st.tabs(names)):
        with tab:
            text = FINANCIAL_VALUATION_GUIDE if (name == "Valuation" and fin is not None) else TAB_GUIDE.get(name)
            if text:
                html(guide(text, "In this tab"))
            for title, fn in groups.get(name, []):
                n, name_ = title.split(". ", 1)
                html(f"<h4><span class='vt-sec-n'>{esc(n)}</span> {esc(name_)}</h4>")
                try:
                    fn(rep)
                except Exception as exc:  # one broken section must not hide the rest of the report
                    st.error(f"This section could not be displayed: {type(exc).__name__}: {exc}")
            if name == "Sources":
                html(f"<h4><span class='vt-sec-n'>{17 if fin is not None else 22}</span> Disclaimer</h4>")
                st.caption(DISCLAIMER)
            for n, fn in extra_tabs or []:
                if n == name:
                    fn()


__all__ = ["render_report", "calc_value", "PER_SHARE"]


# --- history --------------------------------------------------------------------------------------------------------
def what_changed(old: dict, new: dict) -> list[str]:
    """Plain statements of what moved between two versions, largest effects first (code, not AI)."""
    out = []
    names = {"dcf": "DCF", "comps": "peer multiples", "history": "own-history multiples", "sotp": "sum of the parts"}
    for k, label in names.items():
        a, b = (old.get("components") or {}).get(k), (new.get("components") or {}).get(k)
        if a and b and abs(b / a - 1) >= 0.03:
            out.append(f"{label} {money(a)} → {money(b)}")
    if old.get("stage") and new.get("stage") and old["stage"] != new["stage"]:
        out.append(f"stage {old['stage']} → {new['stage']}")
    for k, label, tol in (("wacc", "WACC", 0.001), ("growth", "year-1 growth", 0.005), ("margin", "target margin", 0.005)):
        a, b = old.get(k), new.get(k)
        if a is not None and b is not None and abs(b - a) >= tol:
            out.append(f"{label} {a:.1%} → {b:.1%}")
    a, b = old.get("price"), new.get("price")
    if a and b and abs(b / a - 1) >= 0.02:
        out.append(f"price {money(a)} → {money(b)}")
    return out


# --- what if --------------------------------------------------------------------------------------------------------
def what_if(rep) -> None:
    """Drag the DCF's main drivers and watch the fair value move. Each change reprices the model in Python (the
    comps and own-history legs are held); nothing is saved and the AI commentary is not rewritten."""
    from engine.news_impact import reprice
    from engine.scenarios import implied_wacc
    m = rep.model
    v = m.valuation
    if v is None or v.dcf_inputs is None or getattr(m, "financial", None) is not None:
        st.caption("What if is available for DCF valuations (not the bank, insurer and REIT toolkits).")
        return
    plan, i = v.plan, m.inputs
    rf, price = i.risk_free.value, i.price.value
    base_path = plan.path("revenue_growth")
    key = f"wi_{rep.report_id}"
    base = {"wacc": v.wacc.wacc.value, "g": plan.terminal_growth.value,
            "m": plan.drivers["operating_margin"].chosen.value, "roic": plan.terminal_roic.value, "shift": 0.0}
    base = {k: round(x * 100, 1) for k, x in base.items()}
    for k, x in base.items():
        st.session_state.setdefault(f"{key}_{k}", x)

    roic_now = rep.company.analysis.metrics.get("roic", {}).get(rep.company.historicals.fy_labels[-1])
    w_mkt = implied_wacc(v.dcf_inputs, price / (i.adr_ratio or 1))
    presets = {"Base case": base,
               "Sell-side conventions": {**base, "g": round(min(3.0, rf * 100), 1),
                                         "roic": round(max(base["roic"], min((roic_now.value if roic_now else 0) * 100,
                                                                             40.0)), 1)}}
    if w_mkt is not None:
        presets["Market's discount rate"] = {**base, "wacc": round(w_mkt * 100, 1)}

    def bounds(k, lo, hi):  # a slider's range always holds every preset's value
        vals = [x[k] for x in presets.values()]
        return round(min([lo] + vals), 1), round(max([hi] + vals), 1)

    def apply(vals):
        for k, x in vals.items():
            st.session_state[f"{key}_{k}"] = x

    @st.fragment
    def panel():
        cols = st.columns(len(presets))
        for c, (name, vals) in zip(cols, presets.items()):
            c.button(name, key=f"{key}_p_{name}", on_click=apply, args=(vals,), width="stretch")
        c1, c2 = st.columns(2)
        wacc = c1.slider("Discount rate (WACC, %)", *bounds("wacc", max(base["g"] + 0.5, base["wacc"] - 3),
                                                            base["wacc"] + 3), step=0.1, key=f"{key}_wacc")
        g = c1.slider("Terminal growth (%)", *bounds("g", 0.0, min(4.0, rf * 100)), step=0.1, key=f"{key}_g")
        shift = c1.slider("Revenue growth, every forecast year (points vs base)", -5.0, 5.0, step=0.5,
                          key=f"{key}_shift")
        mg = c2.slider("Target operating margin (%)", *bounds("m", max(0.0, base["m"] - 10), base["m"] + 10),
                       step=0.1, key=f"{key}_m")
        roic = c2.slider("Terminal return on capital (%)", *bounds("roic", 4.0, 60.0), step=0.1, key=f"{key}_roic")
        ov = {}
        if wacc != base["wacc"]:
            ov["wacc"] = wacc / 100
        if g != base["g"]:
            ov["terminal_growth"] = g / 100
        if mg != base["m"]:
            ov["target_margin"] = mg / 100
        if roic != base["roic"]:
            ov["terminal_roic"] = roic / 100
        if shift:
            ov["revenue_growth"] = [x + shift / 100 for x in base_path]
        try:
            now, ref = reprice(m, ov), reprice(m, {})
        except Exception as exc:  # RepriceError, or an engine error such as terminal growth at or above WACC
            st.warning(f"These assumptions cannot be valued: {exc}")
            return
        if now.fair_value is None or ref.fair_value is None:
            st.caption("No fair value with these assumptions.")
            return
        move = now.fair_value / ref.fair_value - 1
        gap = now.fair_value / price - 1
        def kpi(label, value, sub, colour=None):  # plain figures: no count-up on every drag
            style = f" style='color:{colour}'" if colour else ""
            return (f"<div class='vt-kpi'><div class='l'>{esc(label)}</div><div class='v'{style}>{esc(value)}</div>"
                    f"<div class='s'>{esc(sub)}</div></div>")
        html("<div class='vt-kpis'>"
             + kpi("Fair value", money(now.fair_value), f"{move:+.1%} vs base {money(ref.fair_value)}", ACCENT)
             + kpi("DCF", money(now.dcf_value), "probability-weighted scenarios")
             + kpi("Upside", f"{gap:+.1%}", f"vs price {money(price)}", GREEN if gap > 0 else RED)
             + kpi("Verdict", now.verdict or "–", "same rules as the report", VERDICT_COLOUR.get(now.verdict))
             + "</div>")
        html(_range_strip(min(ref.fair_value, now.fair_value), max(ref.fair_value, now.fair_value),
                          "Move from the base", price, now.fair_value, ref.fair_value))
        comps = m.verdict.components
        held = [f"comps {money(comps['comps'])}" if comps.get("comps") else "",
                f"own-history multiples {money(comps['history'])}" if comps.get("history") else ""]
        st.caption("Held while you drag: " + (", ".join(x for x in held if x) or "nothing else")
                   + ". Only the DCF moves; the blend weights are the report's.")
        if abs(ref.fair_value / m.verdict.fair_value - 1) > 0.005:
            st.caption(f"The base here ({money(ref.fair_value)}) is this report's inputs on today's engine; the saved "
                       f"fair value was {money(m.verdict.fair_value)}. Re-run the report to update it.")
    panel()
