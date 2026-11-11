"""AI capex tracker (pure). Capex statements are extracted from filing text by rule, never written by a model: a sentence
qualifies when it names capital spending, looks forward and carries a dollar figure. Each is returned verbatim with the
filing's date and link, so every figure on the panel traces to a source."""
from __future__ import annotations

import html
import re
from datetime import date

HYPERSCALERS = ("MSFT", "AMZN", "GOOGL", "META", "ORCL")
STALE_DAYS = 120
AI_SHARE_THRESHOLD = 0.30

_TOPIC = re.compile(r"capital expenditure|capital spending|\bcapex\b|purchases? of property and equipment|"
                    r"capital investment", re.I)
_FORWARD = re.compile(r"\b(expect|anticipate|outlook|guidance|forecast|plan|project|estimate|will be|range of|"
                      r"to be (?:in|between|approximately)|increase|continue to invest)", re.I)
_MONEY = re.compile(r"\$\s?\d[\d,.]*\s?(?:billion|bn|million|b\b|m\b)?", re.I)
_STRONG = re.compile(r"\b(expects?|anticipates?|anticipated|expected|outlook|guidance|range of|in the range|"
                     r"will invest)\b", re.I)
# a sentence about money already raised or spent, not a forward statement of capex
_HISTORICAL = re.compile(r"proceeds|net cash (?:used|provided)|increased from|decreased from|compared (?:with|to) "
                         r"(?:the )?(?:first|second|third|fourth|prior)|for general corporate purposes", re.I)


def plain_text(raw: str) -> str:
    """HTML or text to one block of plain text (tags and scripts removed, entities decoded, spaces collapsed)."""
    t = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", raw)
    t = re.sub(r"(?s)<[^>]+>", " ", t)
    return " ".join(html.unescape(t).replace("\xa0", " ").replace("•", ". ").replace("·", ". ").split())


def sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+(?=[A-Z“\"(])", text) if s.strip()]


def capex_statements(text: str, limit: int = 3) -> list[str]:
    """Forward-looking capex sentences with a dollar figure, strongest wording first, at most `limit`."""
    hits = [s for s in sentences(plain_text(text)) if 25 <= len(s) <= 600 and _TOPIC.search(s) and _FORWARD.search(s)
            and _STRONG.search(s) and _MONEY.search(s) and not _HISTORICAL.search(s)]
    hits.sort(key=len)
    out: list[str] = []
    seen: set[str] = set()
    for s in hits:
        key = re.sub(r"[\s$]", "", s.lower())  # the same sentence with different spacing is one sentence
        if key not in seen:
            seen.add(key)
            out.append(re.sub(r"[\s.]+$", ".", s))
    return out[:limit]


def age_days(filed: str, today: date) -> int:
    return (today - date.fromisoformat(filed[:10])).days


def ai_revenue_share(research: dict | None, revenue_millions: float | None) -> tuple[float | None, str]:
    """Share of sales from data centre / AI, from the annual report's segments and KPIs (verified extracts). Returns
    (share or None, how). None when the filing gives no such figure: the panel is then not attached."""
    data = research or {}
    biz = data.get("business") or {}
    pat = re.compile(r"data ?cent(?:er|re)|\bAI\b|artificial intelligence|accelerat|compute|cloud", re.I)
    segs = [(s.get("name", ""), s.get("revenue_millions")) for s in biz.get("segments", []) if s.get("revenue_millions")]
    total = sum(r for _, r in segs) or revenue_millions
    match = [(n, r) for n, r in segs if pat.search(n)]
    if match and total:
        share = sum(r for _, r in match) / total
        return share, "segment " + ", ".join(n for n, _ in match)
    for k in biz.get("kpis", []):
        if re.search(r"data ?cent(?:er|re)|\bAI\b", k.get("name", ""), re.I):
            m = re.search(r"\$?\s?([\d,.]+)\s*(billion|bn|million|m)\b", k.get("value_text", ""), re.I)
            if m and revenue_millions:
                v = float(m.group(1).replace(",", "")) * (1000 if m.group(2).lower() in ("billion", "bn") else 1)
                return v / revenue_millions, f"KPI {k['name']}"
    return None, "no data centre or AI revenue figure in the annual report extracts"


def qualifies(research: dict | None, revenue_millions: float | None) -> tuple[bool, float | None, str]:
    share, how = ai_revenue_share(research, revenue_millions)
    return (share is not None and share > AI_SHARE_THRESHOLD), share, how
