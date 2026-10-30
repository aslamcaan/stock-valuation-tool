"""Reported financial-sector KPIs read from the annual report's text (code only, no AI).

Banks no longer tag regulatory capital in XBRL (us-gaap dropped it after 2013), and FFO/AFFO, the combined ratio and
the net interest margin are company-defined measures. So the tool reads them from the 10-K's own tables and
sentences, keeps the verbatim quote, and checks each value against a plausible range. Tables in 10-Ks run
"Label (footnote markers) current-year prior-year ...", so the first figure after the label is the latest year.
"""
from __future__ import annotations

import html
import re
from dataclasses import dataclass

from engine.values import PER_SHARE, RATIO

# whole numbers only: never stop inside "1234.56" or "1,234" (the lookahead rejects a following digit or decimal)
NUM = r"(?P<num>\(?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?\)?)(?![\d]|[.,]\d)"
# between a label and its figure: footnote markers "(a)", quoted abbreviations ("ROTCE"), an approach qualifier,
# a currency sign, or a short linking verb in a sentence ("was", "of")
GAP = (r"(?P<gap>(?:\s*\((?:[a-z0-9]{1,2}|non-GAAP|\"[^\"]{1,40}\")\))*"
       r"(?:\s*[-,]\s*(?:Standardized|Advanced|transitional|fully phased-in)(?: approach)?(?:\s*\([a-z]{1,2}\))*)?"
       r"(?:\s+(?:was|of|at|is|for 20\d{2} (?:was|of)))?\s*:?"
       r"(?:\s*(?:19|20)\d{2}(?=\s))?"  # a column-header year before the figure
       r"\s*(?:US)?\$?\s*)")  # not "were": lists mix figures
EXCLUDE_BEFORE = re.compile(r"(reconciliation of|table \d+:|minimum|required|requirement|requirements|target|"
                            r"guidance|well-capitalized|"
                            r"buffer|excluding|ex-|underlying|adjusted for|effect of|impact of|change in)[^.]{0,40}$",
                            re.IGNORECASE)


@dataclass(frozen=True)
class Spec:
    label: str
    unit: str            # RATIO (written as a percentage), PER_SHARE (US$ per share)
    patterns: tuple[str, ...]
    lo: float
    hi: float
    excluded_after: str = ""   # regex: the label must NOT be followed by this (e.g. "excluding")


SPECS: dict[str, dict[str, Spec]] = {
    "bank": {
        "cet1_ratio": Spec("CET1 ratio", RATIO, (r"CET1 capital ratio", r"Common equity tier 1 \(?(?:\"?CET1\"?\)? )?"
                                                 r"(?:capital )?ratio", r"CET1 ratio"), 0.03, 0.35),
        "tier1_leverage_ratio": Spec("Tier 1 leverage ratio", RATIO, (r"Tier 1 leverage ratio", r"Tier 1 leverage"),
                                     0.02, 0.25),
        "slr": Spec("Supplementary leverage ratio", RATIO, (r"Supplementary leverage ratio(?: \(\"SLR\"\))?", r"SLR"),
                    0.02, 0.20),
        "nim": Spec("Net interest margin", RATIO, (r"Net interest margin", r"Net yield on average interest-earning "
                                                   r"assets(?: - managed basis)?",
                                                   r"Net interest margin \(?(?:FTE|fully taxable-equivalent)\)?"),
                    0.005, 0.10, excluded_after=r"\s*excluding"),
        "rotce": Spec("Return on tangible common equity", RATIO,
                      (r"Return on (?:average )?tangible common (?:shareholders' |stockholders' )?equity",
                       r"ROTCE"), -0.5, 0.6),
        "roe": Spec("Return on common equity", RATIO,
                    (r"Return on (?:average )?common (?:shareholders' |stockholders' )?equity",), -0.5, 0.6),
        "bvps": Spec("Book value per share", PER_SHARE, (r"(?<!angible )Book value per (?:common )?share",), 0.5, 5000),
        "tbvps": Spec("Tangible book value per share", PER_SHARE,
                      (r"Tangible book value per (?:common )?share",), 0.5, 5000),
        "efficiency_ratio": Spec("Efficiency (overhead) ratio", RATIO, (r"Overhead ratio", r"Efficiency ratio",
                                                                         r"Efficiency(?= \d)"),
                                 0.2, 1.5),
    },
    "insurer": {
        "combined_ratio": Spec("Combined ratio", RATIO, (r"(?:P&C )?Combined ratio",), 0.5, 1.6),
        "loss_ratio": Spec("Loss and LAE ratio", RATIO, (r"Loss and loss adjustment expense ratio",
                                                         r"Loss and loss expense ratio", r"Loss ratio"), 0.2, 1.3),
        "expense_ratio": Spec("Underwriting expense ratio", RATIO, (r"Underwriting expense ratio",
                                                                    r"(?<!loss )(?<!administrative )(?<!acquisition cost )Expense ratio"),
                              0.05, 0.6),
        "bvps": Spec("Book value per share", PER_SHARE, (r"(?<!angible )Book value per (?:common )?share",), 0.5, 5000),
    },
    "reit": {
        "ffo_per_share": Spec("FFO per share", PER_SHARE, (r"(?<!Normalized )(?<!Core )FFO per (?:diluted )?(?:common )?"
                                                           r"share", r"Funds from operations per (?:diluted )?share"),
                              0.05, 100),
        "affo_per_share": Spec("AFFO per share", PER_SHARE, (r"AFFO per (?:diluted )?(?:common )?share",
                                                             r"Adjusted funds from operations per (?:diluted )?share"),
                               0.05, 100),
        "occupancy": Spec("Occupancy", RATIO, (r"occupancy (?:in our operating portfolio |rate )?(?:of|was)",
                                               r"portfolio (?:was|is) (?=\d)"), 0.3, 1.0),
    },
}


@dataclass(frozen=True)
class Reported:
    key: str
    label: str
    value: float
    unit: str
    quote: str
    source: str


def plain(raw: str) -> str:
    t = html.unescape(re.sub(r"<[^>]+>", " ", raw))
    for a, b in (("&#160;", " "), ("&nbsp;", " "), ("&#8203;", ""), ("&#8209;", "-"), ("&#8220;", '"'),
                 ("&#8221;", '"'), ("&#8217;", "'"), ("&#8211;", "-"), ("&#8212;", "-"), ("&amp;", "&"),
                 ("“", '"'), ("”", '"'), ("’", "'"), ("–", "-"), ("—", "-"), ("\xa0", " ")):
        t = t.replace(a, b)
    return re.sub(r"\s+", " ", t)


def _value(num: str, unit: str, pct: bool) -> float:
    neg = num.startswith("(") and num.endswith(")")
    x = float(num.strip("()").replace(",", ""))
    x = -x if neg else x
    return x / 100 if unit == RATIO else x


def find(text: str, spec: Spec, ok=lambda v: True) -> tuple[float, str] | None:
    """First figure after one of the labels that is in range (and passes `ok`), not a requirement or an adjusted
    variant."""
    for pat in spec.patterns:
        for m in re.finditer(f"(?:{pat}){GAP}{NUM}(?P<pct>\\s*%)?", text, re.IGNORECASE):
            if EXCLUDE_BEFORE.search(text[max(0, m.start() - 60):m.start()]):
                continue
            label_end = m.start("gap")
            if spec.excluded_after and re.match(spec.excluded_after, text[label_end:label_end + 20], re.I):
                continue
            if spec.unit == PER_SHARE and m.group("pct"):
                continue
            if spec.unit == RATIO and "$" in m.group("gap"):
                continue
            if re.match(r"\s*(?:billion|million|thousand|bn|m)\b", text[m.end():m.end() + 12], re.I):
                continue  # an amount, not a ratio or per-share figure
            if spec.unit == PER_SHARE and re.fullmatch(r"(?:19|20)\d{2}", m.group("num")):
                continue  # a column year, not a value
            v = _value(m.group("num"), spec.unit, bool(m.group("pct")))
            if spec.lo <= v <= spec.hi and ok(v):
                return v, text[m.start():m.end() + 40].strip()
    return None


def reported_kpis(text: str, toolkit: str, source: str) -> dict[str, Reported]:
    out = {}
    for key, spec in SPECS.get(toolkit, {}).items():
        ok = lambda v: True  # noqa: E731
        if key == "tbvps" and "bvps" in out:  # tangible book is below book (rules out stray figures)
            ok = lambda v, b=out["bvps"].value: 0.2 * b <= v <= b  # noqa: E731
        hit = find(text, spec, ok)
        if hit:
            out[key] = Reported(key, spec.label, hit[0], spec.unit, hit[1], source)
    return out
