"""Stock pitch: one A4 page for an interview. A one-line thesis, three supporting points, the valuation (DCF range and what
the price needs), three risks each with an exit condition, a price chart and the sources. Plain layout, no commentary
about how it was made. Every number is the report's own; a missing piece says so instead of being filled in."""
from __future__ import annotations

import re
from io import BytesIO

from reportlab.graphics.shapes import Drawing, Line, PolyLine, String
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from engine.expectations import expectations, risk_reward
from exports.pdf import ACCENT, GREY, INK, LIGHT, RULE, clean

ss = getSampleStyleSheet()
TITLE = ParagraphStyle("pt", parent=ss["Heading1"], fontName="Helvetica-Bold", fontSize=15, leading=18, textColor=INK,
                       spaceAfter=0)
SUB = ParagraphStyle("ps", parent=ss["BodyText"], fontName="Helvetica", fontSize=7.5, leading=9.5, textColor=GREY)
H = ParagraphStyle("ph", parent=ss["Heading2"], fontName="Helvetica-Bold", fontSize=9, leading=11, textColor=INK,
                   spaceBefore=6, spaceAfter=2)
B = ParagraphStyle("pb", parent=ss["BodyText"], fontName="Helvetica", fontSize=8, leading=10)
THESIS = ParagraphStyle("pth", parent=B, fontName="Helvetica-Bold", fontSize=9.5, leading=12)
S = ParagraphStyle("pss", parent=B, fontSize=6.5, leading=8, textColor=GREY)


def P(text, style=B) -> Paragraph:
    return Paragraph(clean(text), style)


def first_sentence(text: str, limit: int = 220) -> str:
    t = " ".join((text or "").split())
    m = re.search(r"(?<=[.!?])\s", t)
    t = t[:m.start()] if m else t
    return t if len(t) <= limit else t[:limit - 1].rstrip() + "…"


def shorten(text: str, limit: int) -> str:
    t = " ".join((text or "").split())
    return t if len(t) <= limit else t[:limit - 1].rstrip() + "…"


def price_chart(closes: list[tuple[str, float]], levels: dict[str, float | None], width: float, height: float) -> Drawing:
    """Daily closes as a line, with the bear, base and bull DCF as dashed levels."""
    d = Drawing(width, height)
    if len(closes) < 2:
        d.add(String(4, height / 2, "No price history available.", fontSize=7, fontName="Helvetica", fillColor=GREY))
        return d
    lv = {k: v for k, v in levels.items() if v}
    ys = [c for _, c in closes] + list(lv.values())
    lo, hi = min(ys), max(ys)
    pad = (hi - lo) * 0.08 or 1.0
    lo, hi = lo - pad, hi + pad
    left, bottom, top = 34.0, 10.0, height - 6.0

    def y(v):
        return bottom + (v - lo) / (hi - lo) * (top - bottom)

    def x(i):
        return left + i / (len(closes) - 1) * (width - left - 4)
    d.add(Line(left, bottom, width - 4, bottom, strokeColor=RULE, strokeWidth=0.5))
    pts = []
    for i, (_, c) in enumerate(closes):
        pts += [x(i), y(c)]
    d.add(PolyLine(pts, strokeColor=INK, strokeWidth=0.9))
    colour = {"Bear DCF": colors.HexColor("#c4302b"), "Base DCF": ACCENT, "Bull DCF": colors.HexColor("#1a7f37")}
    for name, v in lv.items():
        d.add(Line(left, y(v), width - 4, y(v), strokeColor=colour.get(name, GREY), strokeWidth=0.7, strokeDashArray=[3, 2]))
        d.add(String(2, y(v) - 2, f"{v:,.0f}", fontSize=6, fontName="Helvetica", fillColor=colour.get(name, GREY)))
    d.add(String(left, 1, closes[0][0], fontSize=6, fontName="Helvetica", fillColor=GREY))
    d.add(String(width - 4 - 44, 1, closes[-1][0], fontSize=6, fontName="Helvetica", fillColor=GREY))
    d.add(String(width - 4, y(closes[-1][1]) + 3, f"last close {closes[-1][1]:,.0f}", fontSize=6, fontName="Helvetica",
                 fillColor=INK, textAnchor="end"))
    return d


def sources_line(rep) -> str:
    m, cd = rep.model, rep.company
    h = cd.historicals
    price = m.inputs.price
    bits = [f"Financials: SEC filings (latest annual period {h.fy_labels[-1]}"
            + (f", trailing twelve months to {h.ltm.label}" if getattr(h, "ltm", None) else "") + ")",
            f"price: {price.source}, {str(price.period)[:10]}",
            "rates and risk-free: FRED; industry data and equity risk premium: Damodaran",
            "analyst consensus: FMP" if m.inputs.consensus else "no analyst consensus used"]
    return "; ".join(bits) + f". Valuation date {rep.valuation_date}."


def build_pitch(rep, closes: list[tuple[str, float]] | None = None, holding: dict | None = None) -> bytes:
    m, cd = rep.model, rep.company
    p, vd, v = cd.profile, m.verdict, m.valuation
    md = getattr(rep, "md", None)
    view = (md.view if md else {}) or {}
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=14 * mm, rightMargin=14 * mm, topMargin=12 * mm,
                            bottomMargin=12 * mm, title=f"{p.name} ({p.ticker}) stock pitch", author="Stock Valuation Tool")
    s = [P(f"{p.name} ({p.ticker})", TITLE),
         P(f"{p.exchange} · {p.sic_description} · price ${vd.price:,.2f} on {str(m.inputs.price.period)[:10]} · "
           f"{md.rating + ' · ' if md and md.rating else ''}{vd.verdict or ''}", SUB), Spacer(1, 3)]

    thesis = (holding or {}).get("thesis") or view.get("thesis")
    s += [P("Thesis", H), P(first_sentence(thesis) if thesis else "No thesis written yet: add one on the Position tab.",
                            THESIS if thesis else B)]
    lines = [first_sentence(x, 170) for x in (view.get("reasoning_lines") or [])[:3]]
    s.append(P("Supporting points", H))
    for i in range(3):
        s.append(P(f"{i + 1}. " + (lines[i] if i < len(lines) else "Not available for this report."), B))

    # valuation
    s.append(P("Valuation", H))
    rr = risk_reward(rep)
    if rr:
        v_ = rr["values"]
        rows = [["", "Bear DCF", "Base DCF", "Bull DCF", "Price"],
                ["Per share (US$)"] + [f"{v_[k]:,.2f}" if v_[k] else "n/a" for k in ("bear", "base", "bull")] + [f"{vd.price:,.2f}"],
                ["From the price"] + [f"{rr['pct'][k]:+.0%}" if rr["pct"][k] is not None else "n/a" for k in ("bear", "base", "bull")] + [""]]
        t = Table(rows, colWidths=[34 * mm, 30 * mm, 30 * mm, 30 * mm, 30 * mm])
        t.setStyle(TableStyle([("FONTSIZE", (0, 0), (-1, -1), 7.5), ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                               ("BACKGROUND", (0, 0), (-1, 0), LIGHT), ("LINEBELOW", (0, 0), (-1, -1), 0.25, RULE),
                               ("ALIGN", (1, 0), (-1, -1), "RIGHT"), ("TOPPADDING", (0, 0), (-1, -1), 2),
                               ("BOTTOMPADDING", (0, 0), (-1, -1), 2)]))
        s.append(t)
        mc = "n/a" if rr["prob_above_price"] is None else f"{rr['prob_above_price']:.0%}"
        er = "n/a" if rr["expected_return"] is None else f"{rr['expected_return']:+.0%}"
        s.append(P(f"Scenario weights 25/50/25: expected return {er}. Share of 2,000 Monte Carlo runs above the price: {mc}. "
                   f"Fair value (headline): ${vd.fair_value:,.2f}"
                   + (", the scenario-weighted DCF (the blend of methods was not used)." if getattr(vd, "fallback", None)
                      else "."), S))
    else:
        s.append(P("No DCF for this company (bank, insurer or REIT toolkit): see the full report for its valuation.", B))
    e = expectations(rep)
    if e:
        s.append(P("What the price needs: " + " ".join(e["lines"]) + " " + e["base_line"], B))

    # risks and exit conditions
    s.append(P("Risks and exit conditions", H))
    risks = [r for r in (view.get("key_risks") or []) if r.get("risk")][:3]
    mine = list((holding or {}).get("conditions") or [])
    change = list(view.get("what_would_change_view") or [])
    rows = [["Risk (filing quote)", "Exit condition"]]
    for i in range(3):
        if i < len(risks):
            q = f" “{shorten(risks[i].get('quote', ''), 150)}”" if risks[i].get("quote") else ""
            risk = f"{shorten(risks[i]['risk'], 110)}.{q}"
        else:
            risk = "Not available for this report."
        exit_ = mine[i] if i < len(mine) else ("What would change the view: " + shorten(change[i], 140)
                                                if i < len(change) else "Not set.")
        rows.append([P(risk, S), P(exit_, S)])
    t = Table(rows, colWidths=[104 * mm, 78 * mm])
    t.setStyle(TableStyle([("FONTSIZE", (0, 0), (-1, 0), 7.5), ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                           ("BACKGROUND", (0, 0), (-1, 0), LIGHT), ("LINEBELOW", (0, 0), (-1, -1), 0.25, RULE),
                           ("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 2),
                           ("BOTTOMPADDING", (0, 0), (-1, -1), 2)]))
    s.append(t)

    # chart
    s.append(P("Price against the DCF range", H))
    levels = {"Bear DCF": rr["values"]["bear"], "Base DCF": rr["values"]["base"], "Bull DCF": rr["values"]["bull"]} if rr else {}
    s.append(price_chart(closes or [], levels, 182 * mm, 38 * mm))
    s.append(P(sources_line(rep), S))
    s.append(P("Not investment advice. Every figure is computed from the sources above on the valuation date; dashed lines "
               "are per US share.", S))
    doc.build(s)
    return buf.getvalue()
