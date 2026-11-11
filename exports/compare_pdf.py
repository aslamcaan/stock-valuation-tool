"""One landscape A4 page: the ranked compare table (reportlab), with the date and the basis of every column."""
from __future__ import annotations

from datetime import date
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from engine.compare_table import COLUMNS, fmt

SHORT = {"Price (US$)": "Price", "Monte Carlo % above price": "MC > price", "Trailing vs median": "P/E vs med",
         "Own median P/E": "Med P/E", "Expected return": "Exp. return", "Return basis": "Basis", "Price date": "Date"}


def build_compare_pdf(rows: list[dict], today: date | None = None) -> bytes:
    st = getSampleStyleSheet()
    small = ParagraphStyle("s", parent=st["Normal"], fontSize=6.5, leading=8)
    cell = ParagraphStyle("c", parent=st["Normal"], fontSize=6.5, leading=7.5)
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4), leftMargin=10 * mm, rightMargin=10 * mm, topMargin=10 * mm,
                            bottomMargin=10 * mm, title="Compare", author="Stock Valuation Tool")
    head = ["#"] + [SHORT.get(h, h) for _, h, _ in COLUMNS]
    data = [[Paragraph(f"<b>{h}</b>", cell) for h in head]]
    for r in rows:
        data.append([Paragraph(str(r["rank"]), cell)] + [Paragraph(fmt(r[k], kind), cell) for k, _, kind in COLUMNS])
    t = Table(data, repeatRows=1)
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e9e4dc")),
                           ("LINEBELOW", (0, 0), (-1, -1), 0.25, colors.HexColor("#c9c2b8")),
                           ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("TOPPADDING", (0, 0), (-1, -1), 3),
                           ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]))
    when = (today or date.today()).isoformat()
    doc.build([Paragraph("<b>Compare: ranked by expected return</b>", st["Heading2"]),
               Paragraph(f"Saved reports, ranked on {when}. Expected return is the DCF at 25% bear, 50% base and 25% "
                         "bull against the price on the date shown. Trailing P/E is against the company's own median "
                         "over the years of filings available. A dash means the report has no such figure.", small),
               Spacer(1, 4 * mm), t])
    return buf.getvalue()
