"""Data desk: relevant sections of the latest annual report (10-K / 20-F / 40-F) as plain text.

Only Item 1 (Business), Item 1A (Risk Factors), Item 7 (MD&A) and the segment note are sent to the AI, never the
whole filing (PROMPT.md section 3). 20-F equivalents: Item 4 (Information on the Company), Item 3.D (Risk Factors),
Item 5 (Operating and Financial Review). Sections are found by their headings; where a heading appears more than
once (table of contents), the occurrence with the longest body is used.
"""
from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser

SECTION_LIMITS = {"business": 60_000, "risk_factors": 60_000, "mdna": 80_000, "segments": 25_000}

TEN_K = {
    "business": (r"item\s*1\.?\s*business", r"item\s*1a\.?\s*risk\s*factors"),
    "risk_factors": (r"item\s*1a\.?\s*risk\s*factors", r"item\s*1b\.?|item\s*1c\.?|item\s*2\.?\s*properties"),
    "mdna": (r"item\s*7\.?\s*management.{0,5}s\s*discussion", r"item\s*7a\.?|item\s*8\.?\s*financial\s*statements"),
}
TWENTY_F = {
    "business": (r"item\s*4\.?\s*information\s*on\s*the\s*company", r"item\s*4a\.?|item\s*5\.?\s*operating"),
    "risk_factors": (r"(?:item\s*3\.?\s*d\.?|d\.)\s*risk\s*factors", r"item\s*4\.?\s*information\s*on\s*the\s*company"),
    "mdna": (r"item\s*5\.?\s*operating\s*and\s*financial\s*review", r"item\s*6\.?\s*directors"),
}
# Looser headings for integrated annual reports that do not use the Item structure (e.g. ASML)
FALLBACK = {
    "business": (r"(?:our\s+business|business\s+overview|strategic\s+report|our\s+company)",
                 r"(?:risk\s+(?:factors|management)|financial\s+performance|corporate\s+governance)"),
    "mdna": (r"(?:operating\s+and\s+financial\s+review|financial\s+performance|results\s+of\s+operations)",
             r"(?:corporate\s+governance|consolidated\s+financial\s+statements|directors)"),
}
SEGMENT_HEADINGS = r"(?:segment\s+(?:information|reporting|results)|operating\s+segments|reportable\s+segments)"


class _Text(HTMLParser):
    BLOCK = {"p", "div", "br", "tr", "li", "h1", "h2", "h3", "h4", "h5", "h6", "table", "section"}

    def __init__(self):
        super().__init__()
        self.parts: list[str] = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.skip += 1
        if tag in self.BLOCK:
            self.parts.append("\n")
        if tag in ("td", "th"):
            self.parts.append(" | ")

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self.skip:
            self.skip -= 1
        if tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


def html_to_text(raw: str) -> str:
    raw = re.sub(r"<ix:header>.*?</ix:header>", " ", raw, flags=re.S | re.I)  # inline-XBRL hidden facts
    p = _Text()
    p.feed(raw)
    text = html.unescape("".join(p.parts)).replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n\s*\n+", "\n\n", text).strip()


def _section(text: str, start: str, end: str, limit: int) -> str:
    """Headings start a line (cross-references such as "see Item 1. Business" sit mid-sentence and are ignored)."""
    best = ""
    for m in re.finditer(r"(?m)^[ 	]*(?:" + start + ")", text, flags=re.I):
        nxt = re.search(r"(?m)^[ 	]*(?:" + end + ")", text[m.end():], flags=re.I)
        body = text[m.start(): m.end() + (nxt.start() if nxt else limit)]
        if len(body) > len(best):
            best = body
    return best[:limit]


def _segment_note(text: str, limit: int) -> str:
    hits = list(re.finditer(SEGMENT_HEADINGS, text, flags=re.I))
    if not hits:
        return ""
    # the notes to the financial statements come late in the document: prefer the last substantial hit
    for m in reversed(hits):
        chunk = text[m.start(): m.start() + limit]
        if len(re.findall(r"\d", chunk)) > 200:
            return chunk
    return text[hits[-1].start(): hits[-1].start() + limit]


@dataclass
class FilingText:
    form: str
    filing_date: str
    report_date: str
    url: str
    sections: dict[str, str] = field(default_factory=dict)
    fetched_at: str | None = None

    def combined(self) -> str:
        return "\n\n".join(f"<filing section=\"{k}\" form=\"{self.form}\" filed=\"{self.filing_date}\">\n{v}\n</filing>"
                           for k, v in self.sections.items() if v)


def extract_sections(raw_html: str, form: str) -> dict[str, str]:
    text = html_to_text(raw_html)
    spec = TWENTY_F if form.startswith(("20-F", "40-F")) else TEN_K
    out = {name: _section(text, a, b, SECTION_LIMITS[name]) for name, (a, b) in spec.items()}
    for name, (a, b) in FALLBACK.items():
        if len(out.get(name, "")) < 2000:
            out[name] = _section(text, a, b, SECTION_LIMITS[name])
    out["segments"] = _segment_note(text, SECTION_LIMITS["segments"])
    return out


EX13 = re.compile(r"ex-?13|exhibit-?13|annualreport", re.IGNORECASE)


def annual_report_html(svc, cik: int, f) -> tuple[str, str]:
    """(html, fetched_at) of the annual report: the primary document plus any part filed beside it. Some banks
    split the 10-K (e.g. usb-20251231.htm and usb-20251231_d2.htm) or file the financial review as Exhibit 13."""
    doc = svc.edgar.document(cik, f)
    parts = [doc.payload]
    try:
        stem = re.sub(r"(_d\d+)?\.htm$", "", f.primary_document)
        acc = f.accession.replace("-", "")
        for x in svc.edgar.filing_documents(cik, f):
            name = x.get("name", "")
            if name == f.primary_document or not name.endswith(".htm"):
                continue
            if re.fullmatch(re.escape(stem) + r"(_d\d+)?\.htm", name) or EX13.search(name):
                url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc}/{name}"
                parts.append(svc.edgar.raw_xml(url).payload)
    except Exception:  # the primary document alone is still usable
        pass
    return "\n".join(parts), doc.fetched_at_iso


def latest_annual_report(svc, cik: int, years_back: int = 0) -> FilingText | None:
    """The latest annual report, or with `years_back` the one for a fiscal year that many years earlier."""
    filings = svc.edgar.filings(cik, forms={"10-K", "20-F", "40-F"})
    if not filings:
        return None
    f = filings[0]
    if years_back:
        year = int(f.report_date[:4]) - years_back
        f = next((x for x in filings if x.report_date and int(x.report_date[:4]) == year), None)
        if f is None:
            return None
    html_text, fetched = annual_report_html(svc, cik, f)
    return FilingText(f.form, f.filing_date, f.report_date, f.url(cik), extract_sections(html_text, f.form), fetched)
