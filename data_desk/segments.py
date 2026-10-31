"""Segment revenue and operating income read from a filing's XBRL instance (business-segment axis).

Companies tag their segment note in XBRL: KO's five operating segments carry Revenues and OperatingIncomeLoss under
StatementBusinessSegmentsAxis, with ConsolidationItemsAxis = OperatingSegmentsMember (before eliminations); MSFT
tags RevenueFromContractWithCustomerExcludingAssessedTax on the segment axis alone. Reading them here gives
filed numbers rather than the research desk's reading of the text (which missed KO's segment revenues).
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from datetime import date

from core.cache import CacheMiss
from core.http import DataSourceError

XBRLI = "{http://www.xbrl.org/2003/instance}"
XBRLDI = "{http://xbrl.org/2006/xbrldi}"
SEGMENT_AXES = ("StatementBusinessSegmentsAxis", "SegmentsAxis")  # US GAAP, IFRS
REVENUE = ("Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax",
           "RevenueFromContractWithCustomerIncludingAssessedTax", "Revenue")  # in order of preference
OPERATING_INCOME = ("OperatingIncomeLoss", "ProfitLossFromOperatingActivities")
MIN_DAYS = 350  # an annual period
# members that are totals or reconciling items, not segments (srt:ReportableSegmentAggregationBeforeOtherOperating...)
NOT_A_SEGMENT = re.compile(r"Aggregation|Total|Eliminat|Consolidat|Reconcil|Intersegment|AllOther|Unallocat", re.I)


def _local(x: str) -> str:
    return x.rsplit("}", 1)[-1].split(":")[-1]


def member_label(member: str) -> str:
    """'msft:IntelligentCloudMember' -> 'Intelligent Cloud'; 'ko:A.PacificMember' -> 'A. Pacific'."""
    m = _local(member)
    m = re.sub(r"(Segment)?Member$", "", m)
    m = re.sub(r"(?<=[a-z0-9])(?=[A-Z])|(?<=\.)(?=[A-Z])", " ", m)
    return m.strip()


def segment_facts(xml: str | bytes) -> dict[tuple[str, str], dict[str, dict[str, float]]]:
    """{(start, end): {member: {'revenue': .., 'operating_income': ..}}} for annual periods, US$ (or reporting
    currency) units as filed. Contexts count when their only dimensions are the segment axis and, optionally,
    ConsolidationItemsAxis = OperatingSegmentsMember."""
    raw = xml.encode("utf-8") if isinstance(xml, str) else xml
    root = ET.fromstring(raw)
    ctx: dict[str, tuple[str, str, str]] = {}
    for c in root.iter(f"{XBRLI}context"):
        seg = c.find(f"{XBRLI}entity/{XBRLI}segment")
        if seg is None or c.find(f"{XBRLI}scenario") is not None:
            continue
        dims = {_local(m.get("dimension", "")): m.text or "" for m in seg.iter(f"{XBRLDI}explicitMember")}
        if any(True for _ in seg.iter(f"{XBRLDI}typedMember")):
            continue
        axis = next((a for a in SEGMENT_AXES if a in dims), None)
        if axis is None:
            continue
        rest = {k: v for k, v in dims.items() if k != axis}
        if rest and (set(rest) != {"ConsolidationItemsAxis"}
                     or _local(rest["ConsolidationItemsAxis"]) != "OperatingSegmentsMember"):
            continue  # e.g. intersegment eliminations, or a product axis within the segment
        p = c.find(f"{XBRLI}period")
        start, end = p.findtext(f"{XBRLI}startDate"), p.findtext(f"{XBRLI}endDate")
        if not start or not end or (date.fromisoformat(end[:10]) - date.fromisoformat(start[:10])).days < MIN_DAYS:
            continue
        if NOT_A_SEGMENT.search(_local(dims[axis])):
            continue
        ctx[c.get("id")] = (dims[axis], start[:10], end[:10])
    found: dict[tuple[str, str], dict[str, dict[str, dict[str, float]]]] = {}
    for el in root:
        ref = el.get("contextRef")
        if ref not in ctx or el.text is None:
            continue
        concept = _local(el.tag)
        kind = "revenue" if concept in REVENUE else "operating_income" if concept in OPERATING_INCOME else None
        if kind is None:
            continue
        try:
            val = float(el.text.strip()) / 1e6  # millions, as the rest of the tool
        except ValueError:
            continue
        member, start, end = ctx[ref]
        found.setdefault((start, end), {}).setdefault(member, {}).setdefault(kind, {})[concept] = val
    out: dict[tuple[str, str], dict[str, dict[str, float]]] = {}
    for period, members in found.items():
        for member, kinds in members.items():
            row = {}
            for kind, order in (("revenue", REVENUE), ("operating_income", OPERATING_INCOME)):
                vals = kinds.get(kind, {})
                pick = next((c for c in order if c in vals), None)
                if pick is not None:
                    row[kind] = vals[pick]
            out.setdefault(period, {})[member] = row
    return out


def latest_year(facts: dict) -> tuple[str, dict, dict] | None:
    """(end date, {label: row} for the latest annual period with at least two segments with revenue, and the same
    for the year before, which may be empty). Each row: revenue, operating_income (if tagged), growth (if the prior
    year is tagged), member."""
    years = sorted(((s, e), m) for (s, e), m in facts.items()
                   if sum(1 for r in m.values() if r.get("revenue")) >= 2)
    if not years:
        return None
    (start, end), cur = years[-1]
    prior = {}
    for (s, e), m in years[:-1]:
        if abs((date.fromisoformat(end) - date.fromisoformat(e)).days - 365) <= 10:
            prior = m
    rows = {}
    for member, r in cur.items():
        if not r.get("revenue"):
            continue
        before = prior.get(member, {}).get("revenue")
        rows[member_label(member)] = {**r, "member": member,
                                      "growth": r["revenue"] / before - 1 if before else None}
    return end, rows, prior


def _tokens(s: str) -> set[str]:
    stop = {"and", "the", "segment", "segments", "group", "&", "of"}
    return {t for t in re.findall(r"[a-z]+", s.lower()) if t not in stop}


def match_names(xbrl: dict[str, dict], research: list[dict]) -> dict[str, dict]:
    """XBRL segment label -> research segment (for its name and comparables): by identical operating income first,
    then by shared words (EMEA matches 'Europe Middle East Africa' through its initials)."""
    out, used = {}, set()
    for label, r in xbrl.items():
        oi = r.get("operating_income")
        hit = next((i for i, s in enumerate(research) if i not in used and oi is not None
                    and s.get("profit_millions") is not None and abs(s["profit_millions"] - oi) < 0.5), None)
        if hit is None:
            words = _tokens(label)
            initials = "".join(w[0] for w in label.lower().split() if w[0].isalpha())
            best = max(((len(words & _tokens(s.get("name", ""))) + (2 if s.get("name", "").lower() == initials else 0), i)
                        for i, s in enumerate(research) if i not in used), default=(0, None))
            hit = best[1] if best[0] > 0 else None
        if hit is not None:
            used.add(hit)
            out[label] = research[hit]
    return out


def instance_xml(svc, cik: int, filing) -> str | None:
    """The filing's XBRL instance document (SEC serves <name>_htm.xml beside an inline-XBRL filing)."""
    try:
        docs = svc.edgar.filing_documents(cik, filing) or []
        names = [d["name"] for d in docs if d.get("name", "").endswith(".xml")]
        inst = next((n for n in names if n.endswith("_htm.xml")), None) or next(
            (n for n in names if not re.search(r"_(cal|def|lab|pre)\.xml$|FilingSummary", n)), None)
        if inst is None:
            return None
        url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{filing.accession.replace('-', '')}/{inst}"
        return svc.edgar.raw_xml(url).payload
    except (DataSourceError, CacheMiss):
        return None
