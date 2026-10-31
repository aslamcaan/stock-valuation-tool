"""Facts read straight from a filing's XBRL instance, for when SEC's companyfacts API lags the filing.

SEC's companyfacts only carries taxonomies it has processed: TSM's 2025 20-F (filed 2026-04-16) uses the IFRS
2025-03-27 taxonomy, and companyfacts kept just its dei facts. The filing's own instance document (SEC publishes it
as <name>_htm.xml next to an inline-XBRL filing) has every fact, so it is converted to the companyfacts shape and
merged in. Only facts without dimensions are kept (company totals, as in companyfacts).
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET

TAXONOMIES = ("us-gaap", "ifrs-full", "dei", "srt")
XBRLI = "{http://www.xbrl.org/2003/instance}"
SOURCE = "SEC EDGAR filing (XBRL instance)"


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _unit_name(unit) -> str | None:
    """companyfacts names: 'USD', 'shares', 'USD/shares', 'pure'."""
    measures = [m.text.split(":")[-1] for m in unit.iter(f"{XBRLI}measure") if m.text]
    divide = unit.find(f"{XBRLI}divide")
    if divide is not None:
        num = [m.text.split(":")[-1] for m in divide.find(f"{XBRLI}unitNumerator").iter(f"{XBRLI}measure")]
        den = [m.text.split(":")[-1] for m in divide.find(f"{XBRLI}unitDenominator").iter(f"{XBRLI}measure")]
        return f"{num[0]}/{den[0]}" if num and den else None
    return measures[0] if len(measures) == 1 else None


def instance_facts(xml: str, accn: str, form: str, filed: str, fy: int) -> dict:
    """{'facts': {taxonomy: {concept: {'units': {unit: [row, ...]}}}}}; rows as in companyfacts."""
    root = ET.fromstring(xml.encode("utf-8") if isinstance(xml, str) else xml)
    ns = {prefix: uri for prefix, uri in re.findall(r'xmlns:([\w-]+)="([^"]+)"', xml[:20000])}
    tax_of = {uri: prefix for prefix, uri in ns.items() if prefix in TAXONOMIES}
    contexts = {}
    for c in root.iter(f"{XBRLI}context"):
        if c.find(f"{XBRLI}entity/{XBRLI}segment") is not None or c.find(f"{XBRLI}scenario") is not None:
            continue  # dimensional (segment, class of stock ...): not a company total
        p = c.find(f"{XBRLI}period")
        inst, start, end = (p.findtext(f"{XBRLI}{k}") for k in ("instant", "startDate", "endDate"))
        contexts[c.get("id")] = {"end": inst} if inst else {"start": start, "end": end}
    units = {u.get("id"): _unit_name(u) for u in root.iter(f"{XBRLI}unit")}
    out: dict = {}
    seen = set()
    for el in root:
        uri = el.tag[1:].split("}")[0] if el.tag.startswith("{") else ""
        tax = tax_of.get(uri)
        ctx = contexts.get(el.get("contextRef"))
        if tax is None or ctx is None or el.text is None:
            continue
        unit = units.get(el.get("unitRef")) if el.get("unitRef") else None
        try:
            val = float(el.text.strip())
        except ValueError:
            continue  # text facts (dei names, dates)
        if unit is None:
            continue
        key = (tax, _local(el.tag), unit, ctx.get("start"), ctx["end"])
        if key in seen:  # inline XBRL repeats a fact wherever the figure appears
            continue
        seen.add(key)
        row = {**ctx, "val": int(val) if val.is_integer() else val, "accn": accn, "fy": fy, "fp": "FY",
               "form": form, "filed": filed, "src": SOURCE}
        out.setdefault(tax, {}).setdefault(_local(el.tag), {"units": {}})["units"].setdefault(unit, []).append(row)
    return {"facts": out}


def merge(payload: dict, extra: dict) -> dict:
    """companyfacts payload with the instance's rows added (the extractor prefers the latest filing per period)."""
    facts = {tax: {c: {**d, "units": {u: list(rows) for u, rows in d.get("units", {}).items()}}
                   for c, d in concepts.items()} for tax, concepts in payload.get("facts", {}).items()}
    for tax, concepts in extra["facts"].items():
        for concept, d in concepts.items():
            tgt = facts.setdefault(tax, {}).setdefault(concept, {"units": {}})["units"]
            for unit, rows in d["units"].items():
                have = {(r.get("accn"), r.get("start"), r["end"]) for r in tgt.get(unit, [])}
                # companyfacts may already hold some of the filing's facts (e.g. its dei cover page): never twice
                tgt.setdefault(unit, []).extend(r for r in rows if (r["accn"], r.get("start"), r["end"]) not in have)
    return {**payload, "facts": facts}
