"""Research desk (AI, Haiku): reads the relevant annual-report sections and extracts facts with verbatim quotes.

Code then verifies every quote appears in the filing text and every number in an extracted field appears in the
source; anything that fails is dropped and logged. The AI never calculates.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from desks.ai import HAIKU, AIClient

_S = {"type": "string"}
_N = {"type": ["number", "null"]}


def _obj(props: dict) -> dict:
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}


def _arr(item: dict) -> dict:
    return {"type": "array", "items": item}


PARTS = {
    "business": _obj({
        "business_summary": _S,
        "business_quote": _S,
        "segments": _arr(_obj({"name": _S, "description": _S, "revenue_millions": _N, "profit_millions": _N,
                               "profit_metric": _S, "fiscal_year": _S, "quote": _S,
                               "comparable_us_tickers": _arr(_S)})),
        "geographic_mix": _arr(_obj({"region": _S, "share_of_revenue_pct": _N, "revenue_millions": _N,
                                     "quote": _S})),
        "kpis": _arr(_obj({"name": _S, "value_text": _S, "period": _S, "quote": _S})),
        "volume_kpi": _obj({"name": _S, "values": _arr(_obj({"fiscal_year": _S, "value_millions": _N})),
                            "quote": _S}),
    }),
    "risks": _obj({
        "risk_factors": _arr(_obj({"title": _S, "summary": _S, "quote": _S})),
        "one_off_items": _arr(_obj({"description": _S, "amount_millions": _N, "fiscal_year": _S,
                                    "effect": {"type": "string", "enum": ["charge", "gain"]},
                                    "in_operating_income": {"type": "boolean"}, "quote": _S})),
        "guidance": _arr(_obj({"metric": _S, "guidance_text": _S, "period": _S, "quote": _S})),
    }),
    "structure": _obj({
        "convertible_debt": _obj({"present": {"type": "boolean"}, "quote": _S}),
        "share_classes": _obj({"multiple": {"type": "boolean"}, "description": _S, "quote": _S}),
        "key_customers": _arr(_S), "key_suppliers": _arr(_S), "regulators": _arr(_S),
        "commodity_sensitivities": _arr(_obj({"commodity": _S, "sensitivity_text": _S, "quote": _S})),
        "interest_rate_sensitivity": _obj({"text": _S, "quote": _S}),
        "fx_exposure": _obj({"text": _S, "quote": _S}),
    }),
}
PART_FOCUS = {"business": "Extract only: business_summary, business_quote, segments, geographic_mix, kpis, volume_kpi.",
              "risks": "Extract only: risk_factors, one_off_items, guidance.",
              "structure": "Extract only: convertible_debt, share_classes, key customers / suppliers / regulators, "
                           "commodity_sensitivities, interest_rate_sensitivity, fx_exposure."}

SYSTEM = """You are the research desk of an equity research team. You read sections of a company's latest annual
report and extract facts for the analysts. Rules:
- Use only the filing text provided. If something is not in the text, return an empty string, empty list or null.
- Every "quote" must be copied verbatim from the filing text (one or two sentences, exact wording). Do not paraphrase.
- Numbers must be copied exactly as the filing states them (convert to millions of the reporting currency only when
  the filing states a figure in thousands or billions). Never calculate, estimate or infer a number.
- segments: the reportable segments with their latest-year revenue and the segment profit measure the filing uses
  (e.g. Segment Adjusted EBITDA), and up to 3 US-listed companies whose business best matches each segment (tickers).
- geographic_mix: revenue by country or region for the latest year as disclosed.
- kpis: operating KPIs the company reports (e.g. Gross Bookings, users, take rate), latest values with period.
- volume_kpi: the one money-volume metric revenue is earned on, if the company reports it (Gross Bookings, GMV,
  total payment volume, gross transaction value), with its value for EACH fiscal year the filing shows, in millions
  of the reporting currency, and a verbatim quote containing at least one of the values. Empty name and values if
  the company reports no such metric.
- risk_factors: the 6 most material risks for valuation, each with a verbatim quote.
- one_off_items: impairments, restructuring, litigation, gains or losses on investments or disposals, and similar
  items called out as unusual, with the amount (positive number), whether it reduced profit ("charge") or
  increased it ("gain"), the fiscal year, and whether it sits inside operating income.
- guidance: any forward-looking targets management gives.
- convertible_debt / share_classes: whether convertible notes or multiple share classes exist, with a quote."""


@dataclass
class ResearchResult:
    data: dict
    dropped: list[str] = field(default_factory=list)
    sections_found: dict[str, int] = field(default_factory=dict)
    source: str = ""


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.replace("’", "'").replace("“", '"').replace("”", '"')).strip().lower()


def _numbers(s: str) -> list[str]:
    return [x.replace(",", "") for x in re.findall(r"\d[\d,]*(?:\.\d+)?", s or "")]


def verify(data: dict, source_text: str) -> tuple[dict, list[str]]:
    """Drop items whose quote is not verbatim in the source, or whose numbers do not appear in the source."""
    src = _norm(source_text)
    # whole number tokens in the filing ("1,180" -> "1180"; "18" does not match inside "2018" or "1,180")
    src_tokens = {t.replace(",", "") for t in re.findall(r"(?<![\d.,])\d[\d,]*(?:\.\d+)?(?![\d])", src)}
    src_tokens |= {t.rstrip("0").rstrip(".") for t in src_tokens if "." in t}
    dropped: list[str] = []

    def quote_ok(q: str) -> bool:
        return not q or _norm(q) in src

    def nums_ok(item: dict) -> bool:
        for k, v in item.items():
            if k == "quote" or k == "fiscal_year" or k == "period":
                continue
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                txt = f"{v:g}"
                alts = {txt, f"{v:,.0f}".replace(",", ""), f"{v:.1f}", f"{v * 1000:,.0f}".replace(",", ""),
                        f"{v / 1000:g}", f"{v / 1000:.1f}"}  # the filing may state it in billions
                if not any(a in src_tokens for a in alts):
                    return False
            elif isinstance(v, str) and k.endswith("_text"):
                if any(n not in src_tokens for n in _numbers(v)):
                    return False
        return True

    out = dict(data)
    for key in ("segments", "geographic_mix", "kpis", "risk_factors", "one_off_items", "guidance",
                "commodity_sensitivities"):
        kept = []
        for item in data.get(key, []):
            if not quote_ok(item.get("quote", "")):
                dropped.append(f"{key}: '{item.get('name') or item.get('title') or item.get('description') or item.get('region') or item.get('metric')}' quote not found in the filing")
            elif not nums_ok(item):
                dropped.append(f"{key}: '{item.get('name') or item.get('description') or item.get('region') or item.get('metric')}' contains a number not in the filing")
            else:
                kept.append(item)
        out[key] = kept
    for key in ("convertible_debt", "share_classes", "interest_rate_sensitivity", "fx_exposure"):
        item = dict(data.get(key, {}))
        if item.get("quote") and not quote_ok(item["quote"]):
            dropped.append(f"{key}: quote not found in the filing")
            item["quote"] = ""
            if "present" in item:
                item["present"] = False
            if "multiple" in item:
                item["multiple"] = False
        out[key] = item
    vk = dict(data.get("volume_kpi") or {})
    if vk.get("values"):
        if not vk.get("quote") or not quote_ok(vk["quote"]):
            dropped.append(f"volume_kpi: '{vk.get('name')}' quote not found in the filing")
            vk["values"] = []
        else:
            good = [x for x in vk["values"] if x.get("value_millions") is not None and nums_ok(x)]
            if len(good) < len(vk["values"]):
                dropped.append(f"volume_kpi: {len(vk['values']) - len(good)} '{vk.get('name')}' values not found "
                               "in the filing")
            vk["values"] = good
    out["volume_kpi"] = vk
    if not quote_ok(data.get("business_quote", "")):
        out["business_quote"] = ""
        dropped.append("business_quote not found in the filing")
    return out, dropped


def run_research(ai: AIClient, report_id: str, company: str, ticker: str, filing) -> ResearchResult:
    """`filing` is a data_desk.filings.FilingText."""
    sections = {k: len(v) for k, v in filing.sections.items()}
    if not any(sections.values()):
        return ResearchResult({}, ["no annual-report sections could be extracted"], sections)
    content = (f"Company: {company} ({ticker}). Annual report: {filing.form} filed {filing.filing_date} for the "
               f"period ending {filing.report_date}.\n\n{filing.combined()}")
    data: dict = {}
    for part, schema in PARTS.items():  # three smaller schemas: one large schema exceeds the grammar limit
        data.update(ai.call(report_id=report_id, desk="Research desk", model=HAIKU, system=SYSTEM,
                            content=f"{PART_FOCUS[part]}\n\n{content}", schema=schema, effort="low",
                            max_tokens=12000))
    data, dropped = verify(data, "\n".join(filing.sections.values()))
    return ResearchResult(data, dropped, sections, f"{filing.form} filed {filing.filing_date} ({filing.url})")
