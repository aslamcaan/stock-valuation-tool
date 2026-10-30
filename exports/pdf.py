"""PDF report (reportlab): the report as a clean, printable document."""
from __future__ import annotations

from io import BytesIO

from reportlab.graphics.shapes import Drawing, Line, Rect, String
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from engine.rubric import LABELS, WEIGHTS
from ui.format import millions, money, mult, pct
from ui.report import DISCLAIMER

BLUE = colors.HexColor("#0969da")
GREY = colors.HexColor("#57606a")
LIGHT = colors.HexColor("#eaeef2")
REPLACE = {"→": "->", "≥": ">=", "≤": "<=", "×": "x", "−": "-", " ": " ", "◌": "", "✓": "", "✗": ""}

ss = getSampleStyleSheet()
H1 = ParagraphStyle("h1", parent=ss["Heading1"], fontSize=16, spaceAfter=4)
H2 = ParagraphStyle("h2", parent=ss["Heading2"], fontSize=12, spaceBefore=8, spaceAfter=4, textColor=BLUE)
BODY = ParagraphStyle("body", parent=ss["BodyText"], fontSize=8.5, leading=11)
SMALL = ParagraphStyle("small", parent=BODY, fontSize=7, textColor=GREY, leading=9)


def clean(s) -> str:
    s = "" if s is None else str(s)
    for a, b in REPLACE.items():
        s = s.replace(a, b)
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def P(text, style=BODY) -> Paragraph:
    return Paragraph(clean(text), style)


def table(rows, header, widths=None) -> Table:
    data = [[P(h, SMALL) for h in header]] + [[P(c) for c in r] for r in rows]
    t = Table(data, colWidths=widths, repeatRows=1)
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), LIGHT), ("LINEBELOW", (0, 0), (-1, 0), 0.6, GREY),
                           ("LINEBELOW", (0, 1), (-1, -1), 0.2, LIGHT), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                           ("LEFTPADDING", (0, 0), (-1, -1), 3), ("RIGHTPADDING", (0, 0), (-1, -1), 3),
                           ("TOPPADDING", (0, 0), (-1, -1), 1.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5)]))
    return t


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
                   fillColor=BLUE if "DCF" in b.method else colors.HexColor("#8c959f"), strokeColor=None))
    for val, colour, text in ((price, colors.HexColor("#cf222e"), f"Price {money(price)}"),
                              (fv, colors.HexColor("#1a7f37"), f"Fair value {money(fv)}")):
        if val:
            d.add(Line(x(val), 8, x(val), height - 10, strokeColor=colour, strokeWidth=1))
            d.add(String(x(val) + 2, height - 10, text, fontSize=6.5, fillColor=colour))
    return d


def build_pdf(rep) -> bytes:
    m, cd = rep.model, rep.company
    v, vd = m.valuation, m.verdict
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=14 * mm, rightMargin=14 * mm, topMargin=14 * mm,
                            bottomMargin=14 * mm, title=f"{cd.profile.name} ({cd.profile.ticker})")
    s = []
    s.append(P(f"{cd.profile.name} ({cd.profile.ticker})", H1))
    s.append(P(f"{cd.profile.exchange} · {cd.profile.sic_description} · report {rep.report_id} · {rep.created_at} UTC",
               SMALL))
    # 0. verdict card
    card = [["Share price", money(vd.price), "Fair value", f"{money(vd.fair_value)} ({vd.gap:+.1%})" if vd.gap is not None else "-"],
            ["Verdict", vd.verdict or "-", "Confidence", vd.confidence or "-"],
            ["MD rating", rep.md.rating if rep.md else "-", "Conviction", rep.md.conviction if rep.md else "-"],
            ["Stage", v.classification.stage_label, "Toolkit", v.classification.toolkit] if v is not None else
            ["Toolkit", f"{m.financial.toolkit} (no DCF)", "Cost of equity", pct(m.financial.cost_of_equity.value)]]
    if v is not None and len(v.scenarios) == 3:
        b, base, bu = (v.per_us_share(x.value_per_share) for x in v.scenarios)
        card.append(["Bear / base / bull", f"{money(b)} / {money(base)} / {money(bu)}", "Analyst target",
                     f"{money((m.analyst_targets or {}).get('median'))}" if m.analyst_targets else "not available"])
    s.append(table(card, ["", "", "", ""], [32 * mm, 55 * mm, 32 * mm, 55 * mm]))
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
                   + (f"; MD moved to {rep.md.rating}: {view.get('notch_reason')}" if rep.md.rating != rep.md.code_rating else "")))
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
    s.append(table([[ln.replace("_", " ").capitalize()] + [millions(h.v(ln, p)) for p in cols] for ln in lines],
                   ["Line"] + cols, [60 * mm] + [30 * mm] * len(cols)))
    # 4. analysis commentary
    s.append(P("4. Financial analysis", H2))
    for section, lines_ in cd.analysis.commentary.items():
        if lines_:
            s.append(P(f"<b>{section.replace('_', ' ').capitalize()}:</b> " + clean(" ".join(lines_)), BODY))
    s.append(PageBreak())
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
    s.append(table([[x.label, mult(x.low), mult(x.median), mult(x.high), mult(x.current), money(x.implied_price)]
                    for x in m.history.values()], ["Own history", "Low", "Median", "High", "Now", "Implied"],
                   [40 * mm, 22 * mm, 22 * mm, 22 * mm, 22 * mm, 30 * mm]))
    rv = v.reverse or {}
    if rv.get("growth", {}).get("solved"):
        s.append(P(f"13. Reverse DCF: the price implies {pct(rv['growth']['implied_cagr'])} revenue CAGR over "
                   f"{rv['years']} years (base case {pct(rv['base_cagr'])})."))
    s.append(P("14. Scenarios and sensitivity", H2))
    s.append(table([[x.scenario.name, f"{x.scenario.probability:.0%}", x.scenario.describe(),
                     money(v.per_us_share(x.value_per_share)) if x.result else "-"] for x in v.scenarios],
                   ["Scenario", "Prob.", "Assumptions", "Value"], [20 * mm, 14 * mm, 118 * mm, 30 * mm]))
    s1 = v.sensitivity_wacc_growth
    if s1:
        s.append(table([[pct(g)] + [money(v.per_us_share(x)) for x in r] for g, r in zip(s1["terminal_growth"], s1["value_per_share"])],
                       ["g \\ WACC"] + [pct(x) for x in s1["wacc"]], [24 * mm] + [31 * mm] * 5))
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
    s.append(table([[ln.replace("_", " ").capitalize()] + [millions(h.v(ln, p)) for p in cols]
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
    s.append(PageBreak())
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
    s.append(PageBreak())
    if rep.review:
        s.append(P(f"{n(18)}. Review desk notes", H2))
        s.append(table([[c["assumption"], c["severity"], c["challenge"], c["resolution"]]
                        for c in rep.review.get("challenges", [])], ["Assumption", "Severity", "Challenge", "Resolution"],
                       [30 * mm, 15 * mm, 75 * mm, 62 * mm]))
        bc = rep.review.get("bear_case", {})
        s.append(P(f"<b>Bear case.</b> {clean(bc.get('thesis', ''))}", BODY))
        for x in bc.get("points", []):
            s.append(P(f"• {x}"))
        if rep.md:
            s.append(P(f"<b>MD response.</b> {clean(rep.md.view.get('bear_case_response', ''))}", BODY))
    s.append(P(f"{n(19)}. Main risks", H2))
    items = (rep.md.view.get("key_risks") if rep.md else None) or \
            [{"risk": x["title"], "quote": x["quote"]} for x in (rep.research.data.get("risk_factors", []) if rep.research else [])]
    for x in items:
        s.append(P(f"• <b>{clean(x['risk'])}</b> - \"{clean(x.get('quote', ''))}\"", BODY))
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
    doc.build(s)
    return buf.getvalue()
