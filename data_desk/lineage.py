"""Successor issuers (code only): a holding-company reorganisation gives the listed ticker a NEW CIK with no annual
history (e.g. XOM: ExxonMobil Holdings Corp, CIK 2115436, 8-K12B on 2026-07-01; history under Exxon Mobil Corp,
CIK 34088). The predecessor is found from the Commission File Number printed on the 8-K12B cover page, resolved with
EDGAR's file-number search; a small sourced table covers cases that don't resolve. The two XBRL fact sets are
merged only if the periods they share agree, and every number keeps the CIK it came from.
"""
from __future__ import annotations

import re

SUCCESSOR_FORMS = re.compile(r"^8-K12(B|G3)(/A)?$")
FILE_NO = re.compile(r"\b0{0,2}1-\d{4,6}\b")
OVERLAP_TOLERANCE = 0.005
# successor CIK -> (predecessor CIK, source): used when the cover page does not resolve to exactly one predecessor
KNOWN = {2115436: (34088, "8-K12B 0001193125-26-291990 filed 2026-07-01 (Exxon Mobil Corporation, predecessor "
                          "registrant)")}
BROWSE = "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&filenum={fn}&output=atom&count=1"


def annual_fact_count(payload: dict) -> int:
    return sum(1 for ns in payload.get("facts", {}).values() for c in ns.values() for u in c.get("units", {}).values()
               for x in u if x.get("form") in ("10-K", "20-F", "40-F", "10-K/A", "20-F/A"))


def successor_filing(sub: dict) -> dict | None:
    r = sub.get("filings", {}).get("recent", {})
    for i, form in enumerate(r.get("form", [])):
        if SUCCESSOR_FORMS.match(form or ""):
            return {"form": form, "accession": r["accessionNumber"][i], "document": r["primaryDocument"][i],
                    "filed": r["filingDate"][i]}
    return None


def _plain(html: str) -> str:
    t = re.sub(r"<[^>]+>", " ", html)
    t = re.sub(r"&#160;|&nbsp;|&#8203;", " ", t)
    return re.sub(r"\s+", " ", t)


def find_predecessor(svc, cik: int, sub: dict) -> tuple[int | None, str]:
    """(predecessor CIK, how it was found) for a successor issuer, or (None, reason)."""
    f = successor_filing(sub)
    if f is None:
        return None, "no successor-issuer filing (8-K12B / 8-K12G3)"
    acc = f["accession"].replace("-", "")
    url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/{f['document']}"
    own = set(sub.get("filings", {}).get("recent", {}).get("fileNumber", []))
    found: set[int] = set()
    try:
        cover = _plain(svc.edgar.raw_xml(url).payload)[:4000]
        for fn in dict.fromkeys(FILE_NO.findall(cover)):
            if fn in own:
                continue
            atom = svc.edgar.raw_xml(BROWSE.format(fn=fn)).payload
            m = re.search(r"<cik>\s*0*(\d+)\s*</cik>", atom)
            if m and int(m.group(1)) != cik:
                found.add(int(m.group(1)))
    except Exception as exc:  # fall back to the table
        if cik in KNOWN:
            return KNOWN[cik][0], KNOWN[cik][1]
        return None, f"the {f['form']} could not be read ({type(exc).__name__})"
    if len(found) == 1:
        p = found.pop()
        return p, f"{f['form']} filed {f['filed']} (accession {f['accession']}): cover-page file number of CIK {p}"
    if cik in KNOWN:
        return KNOWN[cik][0], KNOWN[cik][1]
    return None, (f"{f['form']} filed {f['filed']} names {len(found)} candidate predecessors" if found else
                  f"{f['form']} filed {f['filed']}: no predecessor file number on the cover page")


def _key(x: dict) -> tuple:
    return x.get("start"), x.get("end"), x.get("fp"), x.get("form"), x.get("accn")


def merge_facts(successor: dict, predecessor: dict, pred_cik: int) -> tuple[dict | None, str]:
    """Union of the two fact sets (each predecessor fact marked with its CIK), or None if shared periods disagree.
    Where both report the same period, both filings are kept: the extractor already takes the latest filed
    (restated) value."""
    checked = bad = 0
    out = {k: v for k, v in successor.items() if k != "facts"}
    facts: dict = {}
    for src, mark in ((predecessor, pred_cik), (successor, None)):
        for ns, concepts in src.get("facts", {}).items():
            for concept, body in concepts.items():
                dst = facts.setdefault(ns, {}).setdefault(concept, {**{k: v for k, v in body.items() if k != "units"},
                                                                    "units": {}})
                for unit, rows in body.get("units", {}).items():
                    lst = dst["units"].setdefault(unit, [])
                    if mark is None:  # successor rows: compare with the predecessor's for the same period
                        prior = {(x.get("start"), x.get("end")): x["val"] for x in lst}
                        for x in rows:
                            v0 = prior.get((x.get("start"), x.get("end")))
                            if v0 is not None and isinstance(v0, (int, float)) and v0:
                                checked += 1
                                bad += abs(x["val"] / v0 - 1) > OVERLAP_TOLERANCE
                    seen = {_key(x) for x in lst}
                    lst += [({**x, "cik": mark} if mark else x) for x in rows if _key(x) not in seen]
    out["facts"] = facts
    if checked and bad / checked > 0.05:
        return None, f"{bad} of {checked} shared figures differ by more than 0.5%: histories not merged"
    return out, f"{checked} shared figures checked; {bad} differ by more than 0.5%"
