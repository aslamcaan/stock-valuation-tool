"""PDF report (reportlab): the report as a clean, printable document."""
from __future__ import annotations

import re
from io import BytesIO

from reportlab.graphics.shapes import Drawing, Line, Rect, String
from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from engine.rubric import LABELS, WEIGHTS
from ui.format import millions, money, mult, pct
from ui.report import DISCLAIMER, with_piotroski
from engine.classify import DECLINING
from engine.insights import peer_regressions, price_walk, return_on_new_capital, tornado, value_split
from ui.insights import dividend_for, ep_for, mc_for, walk_args

INK = colors.HexColor("#14110e")      # masthead warm black, as in the app
ACCENT = colors.HexColor("#d9600b")     # the app's orange, darkened to print and read on white (model figures)
GREY = colors.HexColor("#6b6258")
RULE = colors.HexColor("#d9d0c4")
LIGHT = colors.HexColor("#f6f0e8")
GREEN, RED, AMBER = colors.HexColor("#1a7f37"), colors.HexColor("#c4302b"), colors.HexColor("#9a6700")
VERDICT = {"Undervalued": GREEN, "Overvalued": RED, "Fairly valued": AMBER}
RATING = {"Strong Buy": GREEN, "Buy": GREEN, "Hold": AMBER, "Sell": RED, "Strong Sell": RED}
MASTHEAD = 30 * mm
REPLACE = {"→": "->", "≥": ">=", "≤": "<=", "×": "x", "−": "-", " ": " ", "◌": "", "✓": "", "✗": ""}

ss = getSampleStyleSheet()
H1 = ParagraphStyle("h1", parent=ss["Heading1"], fontName="Helvetica-Bold", fontSize=18, leading=22, textColor=INK,
                    spaceAfter=1)
H2 = ParagraphStyle("h2", parent=ss["Heading2"], fontName="Helvetica-Bold", fontSize=10.5, leading=13, spaceBefore=12,
                    spaceAfter=6, textColor=INK)
BODY = ParagraphStyle("body", parent=ss["BodyText"], fontName="Helvetica", fontSize=8.5, leading=11.5)
SMALL = ParagraphStyle("small", parent=BODY, fontSize=7, textColor=GREY, leading=9)
BODY_R = ParagraphStyle("body_r", parent=BODY, alignment=TA_RIGHT)
SMALL_R = ParagraphStyle("small_r", parent=SMALL, alignment=TA_RIGHT)
_NUM = re.compile(r"[-–+]?\$?\(?-?[\d,]*\.?\d+\)?(%|x|m|bn)?|[-–]|n/a")
KPI_L = ParagraphStyle("kl", parent=SMALL, fontSize=6.5, textColor=GREY)
KPI_V = ParagraphStyle("kv", parent=BODY, fontName="Helvetica-Bold", fontSize=12.5, leading=15)


def _date(ts) -> str:
    from ui.format import when
    return when(ts)


def _pages(rep):
    """Page furniture: a navy masthead on page 1, a running header on later pages, a footer with page numbers."""
    name, ticker = rep.company.profile.name, rep.company.profile.ticker
    w, h = A4

    def footer(c, doc):
        c.setFont("Helvetica", 6.8)
        c.setFillColor(GREY)
        c.drawString(14 * mm, 8 * mm, "Not investment advice. Every figure traces to a dated source: see "
                                      "Assumptions and data provenance.")
        c.drawRightString(w - 14 * mm, 8 * mm, f"Page {doc.page}")

    def first(c, doc):
        c.saveState()
        c.setFillColor(INK)
        c.rect(0, h - MASTHEAD, w, MASTHEAD, stroke=0, fill=1)
        c.setFillColor(colors.HexColor("#ff7a1a"))
        for i, bh in enumerate((2.5, 4.5, 6.5)):  # the app's mark: three rising bars
            c.roundRect(14 * mm + i * 3 * mm, h - 19.5 * mm, 1.8 * mm, bh * mm, 0.8 * mm, stroke=0, fill=1)
        c.setFillColor(colors.white)
        c.setFont("Helvetica-Bold", 9.5)
        c.drawString(25 * mm, h - 14.5 * mm, "STOCK VALUATION TOOL")
        c.setFont("Helvetica", 7.5)
        c.setFillColor(colors.HexColor("#c9bba6"))
        c.drawString(25 * mm, h - 19 * mm, "Equity research note")
        c.drawRightString(w - 14 * mm, h - 14.5 * mm, _date(rep.created_at))
        c.drawRightString(w - 14 * mm, h - 19 * mm, f"Report {rep.report_id}")
        footer(c, doc)
        c.restoreState()

    def later(c, doc):
        c.saveState()
        c.setFont("Helvetica-Bold", 7.5)
        c.setFillColor(INK)
        c.drawString(14 * mm, h - 9 * mm, f"{ticker}  {name}")
        c.setFont("Helvetica", 7.5)
        c.setFillColor(GREY)
        c.drawRightString(w - 14 * mm, h - 9 * mm, f"Stock Valuation Tool · {_date(rep.created_at)}")
        c.setStrokeColor(RULE)
        c.setLineWidth(0.5)
        c.line(14 * mm, h - 11 * mm, w - 14 * mm, h - 11 * mm)
        footer(c, doc)
        c.restoreState()
    return first, later


def clean(s) -> str:
    s = "" if s is None else str(s)
    for a, b in REPLACE.items():
        s = s.replace(a, b)
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def P(text, style=BODY) -> Paragraph:
    return Paragraph(clean(text), style)


def table(rows, header, widths=None) -> Table:
    ncol = max((len(r) for r in rows), default=len(header))
    numeric = [i > 0 and bool(rows) and all(_NUM.fullmatch(str(r[i]).strip()) for r in rows if i < len(r))
               for i in range(ncol)]
    head = [[P(h, SMALL_R if i < ncol and numeric[i] else SMALL) for i, h in enumerate(header)]] if any(header) else []
    data = head + [[P(c, BODY_R if i < ncol and numeric[i] else BODY) for i, c in enumerate(r)] for r in rows]
    t = Table(data, colWidths=widths, repeatRows=1 if head else 0)
    t.setStyle(TableStyle([*([("LINEABOVE", (0, 0), (-1, 0), 0.8, INK), ("LINEBELOW", (0, 0), (-1, 0), 0.5, INK)] if head else []),
                           ("LINEBELOW", (0, 1), (-1, -1), 0.25, RULE), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                           ("LEFTPADDING", (0, 0), (-1, -1), 3), ("RIGHTPADDING", (0, 0), (-1, -1), 3),
                           ("TOPPADDING", (0, 0), (-1, -1), 1.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5)]))
    return t


LINE_LABEL = {"ebitda": "EBITDA", "sbc": "Share-based compensation", "cfo": "Cash from operations",
              "fcf": "Free cash flow", "capex": "Capital expenditure", "eps_diluted": "Diluted EPS"}


def _line(ln: str) -> str:
    return LINE_LABEL.get(ln, ln.replace("_", " ").capitalize())


def _intrinsic(method: str) -> bool:
    return not method.lower().startswith(("comps", "peer", "own history", "52-week", "analyst"))


def football_drawing(rep, width=170 * mm) -> Drawing:
    bars = [b for b in rep.model.football if b.low is not None and b.high is not None]
    price, fv = rep.model.verdict.price, rep.model.verdict.fair_value
    lo = min([b.low for b in bars] + [price] + ([fv] if fv else []))
    hi = max([b.high for b in bars] + [price] + ([fv] if fv else []))
    span = (hi - lo) or 1
    label_w, row_h = 62 * mm, 12
    height = row_h * len(bars) + 30
    d = Drawing(width, height)
    x = lambda v: label_w + (v - lo) / span * (width - label_w - 10)  # noqa: E731
    for i, b in enumerate(bars):
        y = height - 20 - (i + 1) * row_h
        d.add(String(0, y + 2, clean(b.method)[:44], fontSize=6.5, fillColor=GREY))
        d.add(Rect(x(b.low), y, max(x(b.high) - x(b.low), 1), row_h - 4,
                   fillColor=ACCENT if _intrinsic(b.method) else colors.HexColor("#b8ac9c"), strokeColor=None))
    for val, colour, text in ((price, INK, f"Price {money(price)}"), (fv, ACCENT, f"Fair value {money(fv)}")):
        if val:
            d.add(Line(x(val), 8, x(val), height - 10, strokeColor=colour, strokeWidth=1))
            d.add(String(x(val) + 2, height - 10, text, fontSize=6.5, fillColor=colour))
    return d


def build_pdf(rep) -> bytes:
    m, cd = rep.model, rep.company
    v, vd = m.valuation, m.verdict
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=14 * mm, rightMargin=14 * mm, topMargin=16 * mm,
                            bottomMargin=16 * mm, title=f"{cd.profile.name} ({cd.profile.ticker})",
                            author="Stock Valuation Tool")
    p = cd.profile
    s = [Spacer(1, MASTHEAD - 10 * mm), P(p.name, H1), P(f"{p.ticker} · {p.exchange} · {p.sic_description}", SMALL),
         Spacer(1, 6)]
    # 0. rating box: the call first, as on a sell-side note
    rating = rep.md.rating if rep.md else None

    def kpi(label, value, colour=INK):
        return [Paragraph(clean(label).upper(), KPI_L),
                Paragraph(f"<font color='#{colour.hexval()[2:]}'>{clean(value)}</font>", KPI_V)]
    box = Table([[kpi("Rating", rating or "Not rated", RATING.get(rating, GREY)),
                  kpi("Verdict", vd.verdict or "-", VERDICT.get(vd.verdict, INK)),
                  kpi("Share price", money(vd.price)), kpi("Fair value", money(vd.fair_value), ACCENT),
                  kpi("Upside", "-" if vd.gap is None else f"{vd.gap:+.1%}", GREEN if (vd.gap or 0) > 0 else RED)]],
                colWidths=[40 * mm, 40 * mm, 34 * mm, 34 * mm, 34 * mm])
    box.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), LIGHT), ("LINEAFTER", (0, 0), (-2, -1), 0.5, RULE),
                             ("LINEABOVE", (0, 0), (-1, 0), 1.2, INK), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                             ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                             ("LEFTPADDING", (0, 0), (-1, -1), 7)]))
    s += [box, Spacer(1, 6)]
    for note in ([vd.headline_note] if getattr(vd, "headline_note", "") else []) + list(getattr(vd, "top_notes", []) or []):
        s.append(P("Read this first: " + note, SMALL))
    card = [["Confidence", vd.confidence or "-", "Conviction", rep.md.conviction if rep.md else "-"],
            ["Stage", v.classification.stage_label, "Toolkit", v.classification.toolkit] if v is not None else
            ["Toolkit", f"{m.financial.toolkit} (no DCF)", "Cost of equity", pct(m.financial.cost_of_equity.value)]]
    if v is not None and len(v.scenarios) == 3:
        b, base, bu = (v.per_us_share(x.value_per_share) for x in v.scenarios)
        card.append(["Bear / base / bull", f"{money(b)} / {money(base)} / {money(bu)}", "WACC", pct(v.wacc.wacc.value)])
    card.append(["Analyst target", money((m.analyst_targets or {}).get("median")) if m.analyst_targets else
                 "not available", "Price", f"{m.inputs.price.source}, {_date(m.inputs.price.period)}"])
    ne = getattr(getattr(cd, "market", None), "next_earnings", None)
    card.append(["Next results", _date(ne["date"]) if ne and ne.get("date") else "date not known", "", ""])
    s.append(table(card, ["", "", "", ""], [32 * mm, 55 * mm, 32 * mm, 63 * mm]))
    if rep.md:
        for line in rep.md.view.get("reasoning_lines", [])[:4]:
            s.append(P(f"• {line}"))
    if vd.confidence == "Low":
        s.append(P("Low confidence: " + "; ".join(vd.confidence_reasons), SMALL))
    # 1. investment view
    if rep.md:
        view = rep.md.view
        s.append(P("1. Investment view", H2))
        s.append(P(view.get("thesis", "")))
        s.append(table([[LABELS[x.criterion], f"{WEIGHTS[x.criterion]:.0%}", str(x.score), x.by, x.evidence]
                        for x in rep.md.scores], ["Criterion", "Weight", "Score", "By", "Evidence"],
                       [38 * mm, 13 * mm, 11 * mm, 11 * mm, 109 * mm]))
        s.append(P(f"Weighted score {rep.md.weighted_score:.2f} -> {rep.md.code_rating}"
                   + (f"; {rep.md.gate_note}" if getattr(rep.md, "gate_note", "") else
                      f"; MD moved to {rep.md.rating}: {view.get('notch_reason')}" if rep.md.rating != rep.md.code_rating
                      else "")))
        bvb = view.get("bull_vs_bear", {})
        s.append(P(f"Bull vs bear: sides with the {bvb.get('side', '-')} case. {bvb.get('why', '')}"))
        s.append(P("What has to be true: " + " | ".join(view.get("what_has_to_be_true", []))))
        if view.get("catalysts"):
            s.append(table([[c["event"], c["date"], c["why"]] for c in view["catalysts"]], ["Catalyst", "Date", "Why"],
                           [55 * mm, 30 * mm, 97 * mm]))
        s.append(P("What would change our view: " + " | ".join(view.get("what_would_change_view", []))))
        if rep.md.conflict:
            s.append(P(f"Rating vs verdict: {view.get('rating_vs_verdict_explanation', '')}"))
    # 2. business
    if rep.research and rep.research.data:
        d = rep.research.data
        s.append(P("2. Business overview", H2))
        s.append(P(d.get("business_summary", "")))
        if d.get("segments"):
            s.append(table([[x["name"], millions(x.get("revenue_millions")), millions(x.get("profit_millions")),
                             x.get("profit_metric", "")] for x in d["segments"]],
                           ["Segment", "Revenue (m)", "Profit (m)", "Measure"], [60 * mm, 30 * mm, 30 * mm, 62 * mm]))
    if v is None:  # bank / insurer / REIT toolkit
        _financial_body(s, rep)
        return _finish(doc, s, rep, buf)
    # 3. historicals (main lines)
    h = cd.historicals
    cols = [p.label for p in h.periods][-4:]
    s.append(P(f"3. Historicals ({h.currency} m)", H2))
    lines = ["revenue", "operating_income", "net_income_attributable", "ebitda", "sbc", "cfo", "capex", "fcf",
             "cash_and_investments", "total_debt", "total_equity", "shares_diluted_weighted"]
    s.append(table([[_line(ln)] + [millions(h.v(ln, p)) for p in cols] for ln in lines],
                   ["Line"] + cols, [60 * mm] + [30 * mm] * len(cols)))
    # 4. analysis commentary
    s.append(P("4. Financial analysis", H2))
    for section, lines_ in cd.analysis.commentary.items():
        if lines_:
            s.append(Paragraph(f"<b>{section.replace('_', ' ').capitalize()}:</b> " + clean(" ".join(lines_)), BODY))
    fs = with_piotroski(getattr(rep, "forensic", None), rep) or {}
    latest = [x for k in ("beneish", "altman", "piotroski") for x in (fs.get(k) or [])[-1:] if x.value is not None]
    if latest:
        s.append(P("Forensic scores: " + "; ".join(
            f"{x.name} {x.period} {x.value:.0f}" if x.name.startswith("Piotroski") else f"{x.name} {x.period} "
            f"{x.value:.2f}" for x in latest) + " (" + "; ".join(f"{x.name.split()[0]}: {x.reading}" for x in latest)
            + ").", SMALL))
    # 6-7 stage and forecast
    s.append(P("6. Company stage and forecast approach", H2))
    s.append(P(f"{v.classification.stage_label}: {v.classification.stage_reason}."))
    if rep.review:
        cj = rep.review.get("cycle_judgement", {})
        s.append(P(f"Cycle judgement ({cj.get('view', '').replace('_', ' ')}): {cj.get('evidence', '')}"))
    s.append(P("7. Forecast and assumptions", H2))
    rows = []
    for dr in v.plan.drivers.values():
        f = (lambda x: "-" if x is None else f"{x:.2f}x") if dr.name == "sales_to_capital" else (lambda x: "-" if x is None else pct(x))
        rows.append([dr.label, f(dr.history.value if dr.history else None), f(dr.consensus.value if dr.consensus else None),
                     f(dr.industry.value if dr.industry else None), f(dr.chosen.value), dr.source, dr.confidence])
    s.append(table(rows, ["Driver", "History", "Consensus", "Industry", "Chosen", "Source", "Confidence"],
                   [26 * mm, 16 * mm, 16 * mm, 16 * mm, 16 * mm, 76 * mm, 16 * mm]))
    # 9-10 WACC and DCF
    w, i = v.wacc, m.inputs
    s.append(P("9. WACC", H2))
    s.append(table([["Risk-free", pct(i.risk_free.value, 2), "ERP", pct(i.erp.value, 2)],
                    ["Beta used", f"{w.beta.value:.2f}", "Country risk premium", pct(i.crp.value, 2)],
                    ["Cost of equity", pct(w.cost_of_equity.value, 2), "After-tax cost of debt", pct(w.after_tax_cost_of_debt.value, 2)],
                    ["Equity weight", pct(w.weight_equity.value), "WACC", pct(w.wacc.value, 2)]],
                   ["", "", "", ""], [40 * mm, 45 * mm, 50 * mm, 47 * mm]))
    if v.dcf:
        dd = v.dcf
        s.append(P("10. DCF", H2))
        s.append(table([[y.label, millions(y.revenue), pct(y.ebit / y.revenue) if y.revenue else "-", millions(y.nopat),
                         millions(y.reinvestment), millions(y.fcf), millions(y.pv)] for y in dd.years],
                       ["Year", "Revenue", "Margin", "NOPAT", "Reinvest", "FCF", "PV"], [22 * mm] + [26 * mm] * 6))
        s.append(P(f"EV {millions(dd.enterprise_value)} (terminal value {dd.tv_share_of_ev:.0%} of EV); equity "
                   f"{millions(dd.equity_value)}; {v.diluted_shares.value:,.1f}m diluted shares; value per share "
                   f"{money(v.per_us_share(dd.value_per_share))}."))
        sp = value_split(dd, vd.price / v.per_us_share_factor)
        if sp and sp["growth_ev"] >= 0 and sp["market_ev"] > 0:
            s.append(P(f"What the price pays for: today's profits with no growth are worth {millions(sp['no_growth_ev'])} "
                       f"(NOPAT {millions(sp['nopat'])} / WACC {pct(sp['wacc'])}). Growth is "
                       f"{sp['growth_ev'] / dd.enterprise_value:.0%} of our EV and "
                       f"{sp['market_growth_ev'] / sp['market_ev']:.0%} of the market's EV.", SMALL))
        ep, ep_src = ep_for(rep)
        if ep:
            s.append(P(f"Economic profit view: our EV is capital in the business of US${ep['capital']:,.0f}m "
                       f"({ep_src}), plus US${ep['pv_ep']:,.0f}m of economic profit (NOPAT less WACC on capital) over "
                       f"the forecast and US${ep['beyond']:,.0f}m after it, in present value.", SMALL))
        rn = return_on_new_capital(dd)
        if rn:
            s.append(P(f"Return on new capital: the forecast reinvests US${rn['reinvestment']:,.0f}m and NOPAT goes "
                       f"from US${rn['nopat0']:,.0f}m to US${rn['nopat_final']:,.0f}m, "
                       f"{pct(rn['roic_new'])} on the new capital against a {pct(rn['wacc'])} WACC.", SMALL))
    # 11-14
    if v.sotp.applicable:
        s.append(P("11. Sum of the parts", H2))
        s.append(table([[n, millions(ev), how] for n, ev, how in v.sotp.segment_values], ["Segment", "EV", "Basis"],
                       [45 * mm, 30 * mm, 107 * mm]))
    if m.comps:
        s.append(P("12. Comps and historical multiples", H2))
        s.append(table([[x.label, str(len(x.peer_values)), mult(x.median), mult(x.company_value), money(x.implied_price)]
                        for x in m.comps.multiples.values()], ["Multiple", "Peers", "Peer median", "Company", "Implied"],
                       [40 * mm, 20 * mm, 30 * mm, 30 * mm, 30 * mm]))
        s.append(P("Peers: " + ", ".join(p.ticker for p in m.comps.peers), SMALL))
        if m.company_metrics is not None:
            br = sum(x.value for n, x in v.bridge if n != "Long-term investments")
            for r in peer_regressions(m.company_metrics, m.comps.peers, v.diluted_shares.value, br, v.per_us_share_factor):
                if r["applicable"]:
                    s.append(P(f"Warranted {r['label']} at {r['driver']} {pct(r['company_x'])}: {mult(r['warranted'])} "
                               f"(line through {len(r['points'])} peers, R2 {r['r2']:.2f}"
                               + (", extrapolated" if r["extrapolated"] else "") + f") implies "
                               f"{money(r['implied_price'])}, against {money(m.comps.multiples[r['key']].implied_price)} "
                               "at the peer median. A cross-check, not in the fair value.", SMALL))
    s.append(table([[x.label, mult(x.low), mult(x.median), mult(x.high), mult(x.current), money(x.implied_price)]
                    for x in m.history.values()], ["Own history", "Low", "Median", "High", "Now", "Implied"],
                   [40 * mm, 22 * mm, 22 * mm, 22 * mm, 22 * mm, 30 * mm]))
    rv = v.reverse or {}
    if rv.get("growth", {}).get("solved"):
        s.append(P(f"13. Reverse DCF: the price implies {pct(rv['growth']['implied_cagr'])} revenue CAGR over "
                   f"{rv['years']} years (base case {pct(rv['base_cagr'])})."))
    if v.dcf_inputs is not None:
        steps = price_walk(v.dcf_inputs, vd.price / v.per_us_share_factor, *walk_args(rep))
        f = v.per_us_share_factor
        s.append(P("From our DCF to the share price, one assumption at a time (the changes add up to the gap):", SMALL))
        s.append(table([[x["label"], f"{x['change'] * f:+,.2f}" if k else "-", money(x["value"] * f), x["detail"]]
                        for k, x in enumerate(steps)], ["Step", "Change", "Value", "What changed"],
                       [45 * mm, 20 * mm, 22 * mm, 95 * mm]))
        dv, dsrc = dividend_for(rep)
        if dv:
            s.append(P(f"Dividend cross-check: dividends ({money(dv['dps0'] * f)} a share, {dsrc}) growing with the "
                       f"DCF's operating profit after tax for {dv['years']} years, then at "
                       f"{pct(dv['terminal_growth'])}, at a {pct(dv['cost_of_equity'])} cost of equity, are worth "
                       f"{money(dv['value'] * f)}; the price needs {pct(dv['implied_growth'])} dividend growth for "
                       "ever. Ignores buybacks; not in the fair value.", SMALL))
    s.append(P("14. Scenarios and sensitivity", H2))
    s.append(table([[x.scenario.name, f"{x.scenario.probability:.0%}", x.scenario.describe(),
                     money(v.per_us_share(x.value_per_share)) if x.result else "-"] for x in v.scenarios],
                   ["Scenario", "Prob.", "Assumptions", "Value"], [20 * mm, 14 * mm, 118 * mm, 30 * mm]))
    if v.dcf_inputs is not None:
        cap = 0.0 if v.classification.stage == DECLINING else rep.model.inputs.risk_free.value
        rows = tornado(v.dcf_inputs, cap)
        if rows:
            f = v.per_us_share_factor
            s.append(P("Which assumption matters most: each input moved alone to its bear and bull setting.", SMALL))
            s.append(table([[r["label"], f"{r['low_detail']} / {r['high_detail']}", money(r["low"] * f),
                             money(r["high"] * f), f"{(r['high'] - r['low']) * f:,.2f}"] for r in rows],
                           ["Input", "Bear / bull setting", "Bear", "Bull", "Swing"],
                           [38 * mm, 52 * mm, 30 * mm, 30 * mm, 32 * mm]))
    s1 = v.sensitivity_wacc_growth
    if s1:
        s.append(table([[pct(g)] + [money(v.per_us_share(x)) for x in r] for g, r in zip(s1["terminal_growth"], s1["value_per_share"])],
                       ["g \\ WACC"] + [pct(x) for x in s1["wacc"]], [24 * mm] + [31 * mm] * 5))
    if v.dcf_inputs is not None:
        mc, corr, _ = mc_for(rep)
        if mc:
            f = v.per_us_share_factor
            how = (f"growth and margin drawn with their measured correlation of {corr['rho']:+.2f} (from {corr.get('basis', str(corr['n']) + ' years')}), "
                   "WACC and terminal growth independently" if corr else
                   "growth, margin, WACC and terminal growth drawn independently")
            s.append(P(f"Monte Carlo ({mc['valid']:,} DCFs; {how}, each with its 10th-90th percentile range equal to "
                       f"the bear-bull step; fixed seed): median {money(mc['pct'][50] * f)}, 10th-90th "
                       f"{money(mc['pct'][10] * f)} to "
                       f"{money(mc['pct'][90] * f)}; {mc['prob_above_price']:.0%} of versions above the price.", SMALL))
    s.append(P("15. Football field", H2))
    s.append(football_drawing(rep))
    return _finish(doc, s, rep, buf)


def _financial_body(s: list, rep) -> None:
    """Sections 3-10 for the financial-sector toolkits (PROMPT.md section 8)."""
    from engine.financials import method_label
    from ui.financial import FS_LINES
    m, cd, fv = rep.model, rep.company, rep.model.financial
    h = cd.historicals_usd
    cols = h.fy_labels[-4:]
    s.append(P("3. Historicals (US$ m)", H2))
    s.append(table([[_line(ln)] + [millions(h.v(ln, p)) for p in cols]
                    for ln in FS_LINES[fv.toolkit]], ["Line"] + cols, [60 * mm] + [30 * mm] * len(cols)))
    s.append(P(f"4. Sector metrics ({fv.period})", H2))

    def f(x):
        if x is None or x.value is None:
            return "-"
        return money(x.value) if x.unit == "per_share" else (pct(x.value, 2) if x.unit == "ratio" else
                                                             (mult(x.value) if x.unit == "x" else millions(x.value)))
    s.append(table([[mt.group, mt.label, f(mt.value), f(mt.reported)] for mt in fv.metrics],
                   ["Group", "Metric", "Computed", "Reported (10-K)"], [30 * mm, 80 * mm, 36 * mm, 36 * mm]))
    s.append(P("Reported figures are read from the 10-K text; quotes are in the app and the Excel Metrics tab.",
               SMALL))
    s.append(P("6. Toolkit and why no DCF", H2))
    s.append(P(fv.why_no_dcf))
    s.append(P("7. Valuation methods", H2))
    vd = m.verdict
    s.append(table([[method_label(k, fv.toolkit), money(x.value), pct(vd.weights_used.get(k), 0)
                     if k in vd.weights_used else "-"] for k, x in fv.methods.items()],
                   ["Method", "Value per share", "Weight"], [100 * mm, 40 * mm, 40 * mm]))
    d = fv.detail
    if "justified" in d:
        j = d["justified"]
        s.append(P(f"Justified multiple: ({pct(j['return'])} - {pct(j['g'])}) / ({pct(j['coe'])} - {pct(j['g'])}) = "
                   f"{j['multiple']:.2f}x book of {money(j['base'])} per share."))
    if "residual_income" in d:
        ri = d["residual_income"]
        s.append(table([[str(r["year"]), money(r["opening_book"]), pct(r["return"]), money(r["residual_income"]),
                         money(r["pv"])] for r in ri["rows"]], ["Year", "Opening book", "Return", "Residual income",
                                                                "PV"], [20 * mm, 40 * mm, 30 * mm, 46 * mm, 46 * mm]))
        s.append(P(f"Residual income: book {money(ri['rows'][0]['opening_book'])} + PV {money(ri['pv_explicit'])} + "
                   f"PV terminal {money(ri['pv_terminal'])} = {money(ri['value'])}."))
    if "ddm" in d:
        dd = d["ddm"]
        s.append(P(f"Dividend discount: last dividend {money(dd['dps0'])}, stage-1 growth {pct(dd['stage1_growth'])}, "
                   f"long-run {pct(fv.growth.value)}: PV {money(dd['pv_explicit'])} + terminal "
                   f"{money(dd['pv_terminal'])} = {money(dd['value'])}."))
    if "nav" in d:
        n = d["nav"]
        s.append(P(f"NAV: NOI {millions(n['noi'])} / cap rate {pct(n['cap_rate'], 2)} - net debt "
                   f"{millions(n['net_debt'])}."))
    for k in ("comps_pb", "comps_pe", "comps_pffo", "cap_rate"):
        x = d.get(k)
        if x and x.get("peers"):
            s.append(P(f"{'Peer cap rates' if k == 'cap_rate' else method_label(k, fv.toolkit)}: median "
                       f"{'-' if x.get('median') is None else (pct(x['median'], 2) if k == 'cap_rate' else mult(x['median']))}"
                       " (" + ", ".join(p_["ticker"] for p_ in x["peers"]) + ")", SMALL))
    s.append(P("9. Cost of equity", H2))
    i = m.inputs
    s.append(table([["Risk-free", pct(i.risk_free.value, 2), "ERP", pct(i.erp.value, 2)],
                    ["Country risk premium", pct(i.crp.value, 2), "Cost of equity", pct(fv.cost_of_equity.value, 2)],
                    ["Long-run growth", pct(fv.growth.value, 2), "Normalised return",
                     pct(fv.normalised_return.value, 2) if fv.normalised_return else "-"]],
                   ["", "", "", ""], [40 * mm, 45 * mm, 50 * mm, 47 * mm]))
    s.append(P("10. Football field", H2))
    s.append(football_drawing(rep))


def _finish(doc, s: list, rep, buf) -> bytes:
    """Review, risks, flags, provenance and disclaimer (shared by every toolkit)."""
    m = rep.model
    fin = getattr(m, "financial", None) is not None
    n = (lambda k: k - 5) if fin else (lambda k: k)  # financial reports have fewer sections before these
    if rep.review:
        s.append(P(f"{n(18)}. Review desk notes", H2))
        s.append(table([[c["assumption"], c["severity"], c["challenge"], c["resolution"]]
                        for c in rep.review.get("challenges", [])], ["Assumption", "Severity", "Challenge", "Resolution"],
                       [30 * mm, 15 * mm, 75 * mm, 62 * mm]))
        bc = rep.review.get("bear_case", {})
        s.append(Paragraph(f"<b>Bear case.</b> {clean(bc.get('thesis', ''))}", BODY))
        for x in bc.get("points", []):
            s.append(P(f"• {x}"))
        if rep.md:
            s.append(Paragraph(f"<b>MD response.</b> {clean(rep.md.view.get('bear_case_response', ''))}", BODY))
    s.append(P(f"{n(19)}. Main risks", H2))
    items = (rep.md.view.get("key_risks") if rep.md else None) or \
            [{"risk": x["title"], "quote": x["quote"]} for x in (rep.research.data.get("risk_factors", []) if rep.research else [])]
    for x in items:
        s.append(Paragraph(f"• <b>{clean(x['risk'])}</b> - \"{clean(x.get('quote', ''))}\"", BODY))
    s.append(P(f"{n(20)}. Flags", H2))
    s.append(table([[f.level.upper(), f.title, f.message] for f in m.flags], ["Level", "Flag", "Detail"],
                   [18 * mm, 45 * mm, 119 * mm]))
    s.append(P(f"{n(21)}. Assumptions and data provenance", H2))
    s.append(table([[a["group"], a["name"], f"{a['value']:.4g}" if isinstance(a["value"], float) else str(a["value"]),
                     a["source"]] for a in m.assumptions], ["Group", "Assumption", "Value", "Source"],
                   [22 * mm, 50 * mm, 22 * mm, 88 * mm]))
    s.append(table([[x["source"], x["what"], x.get("detail") or "", x.get("fetched_at") or ""] for x in m.sources],
                   ["Source", "What", "Detail", "Fetched"], [35 * mm, 40 * mm, 72 * mm, 35 * mm]))
    s.append(KeepTogether([P(f"{n(22)}. Disclaimer", H2), P(DISCLAIMER, SMALL)]))
    s.append(Spacer(1, 4))
    first, later = _pages(rep)
    doc.build(s, onFirstPage=first, onLaterPages=later)
    return buf.getvalue()
