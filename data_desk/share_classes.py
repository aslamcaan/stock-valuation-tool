"""Share counts by class from a filing's cover page. SEC's companyfacts summary leaves out facts that carry a class
dimension, so a company with several classes (Palantir: A, B and F) can have no cover-page total there; the filing's
own XBRL instance has the count for each class."""
from __future__ import annotations

import re
from itertools import combinations
from types import SimpleNamespace

from core.cache import CacheMiss
from core.http import DataSourceError

PERIODIC_FORMS = ("10-K", "10-Q", "20-F", "40-F")
COVER_TAG = "dei:EntityCommonStockSharesOutstanding"


def latest_periodic_accession(sub: dict) -> str | None:
    """Accession number of the newest annual or quarterly report in a submissions payload."""
    recent = (sub.get("filings") or {}).get("recent") or {}
    for form, acc in zip(recent.get("form", []), recent.get("accessionNumber", [])):
        if form in PERIODIC_FORMS:  # the list is newest first
            return acc
    return None


def class_counts(xml: str) -> tuple[str, dict[str, float]] | None:
    """(cover-page date, {class: shares in millions}) from an XBRL instance; None unless two or more classes."""
    ctx = {}
    for m in re.finditer(r'<(?:xbrli:)?context id="([^"]+)">(.*?)</(?:xbrli:)?context>', xml, re.S):
        members = re.findall(r"<xbrldi:explicitMember[^>]*>([^<]+)<", m.group(2))
        when = re.findall(r"<(?:xbrli:)?(?:instant|endDate)>([^<]+)<", m.group(2))
        if members and when:
            ctx[m.group(1)] = (members[0].split(":")[-1], when[0])
    rows = [(ctx[c][0], ctx[c][1], float(v)) for c, v in re.findall(
        rf'<{COVER_TAG} [^>]*contextRef="([^"]+)"[^>]*>([\d.]+)<', xml) if c in ctx]
    if not rows:
        return None
    latest = max(d for _, d, _ in rows)
    out = {re.sub(r"Member$", "", re.sub(r"^Common", "", name)): v / 1e6 for name, d, v in rows if d == latest}
    return (latest, out) if len(out) >= 2 else None


def one_class_gap(counts: dict[str, float], our_shares: float, provider_shares: float,
                  tol: float = 0.02) -> list[str] | None:
    """The classes whose total matches the provider's implied share count, when the classes together match ours
    (so the provider counted only some of them). None if our count is not confirmed by the cover page or the
    provider's matches no proper subset of the classes."""
    total = sum(counts.values())
    if not our_shares or abs(total / our_shares - 1) > 0.01:
        return None
    names = list(counts)
    for r in range(1, len(names)):
        for subset in combinations(names, r):
            if abs(sum(counts[n] for n in subset) / provider_shares - 1) <= tol:
                return list(subset)
    return None


def cover_counts(svc, cik: int, sub: dict) -> tuple[str, dict[str, float]] | None:
    """Fetch the newest periodic report's XBRL instance and read the class counts (None if not available)."""
    from data_desk.segments import instance_xml

    acc = latest_periodic_accession(sub)
    if acc is None:
        return None
    try:
        xml = instance_xml(svc, cik, SimpleNamespace(accession=acc))
    except (DataSourceError, CacheMiss):
        return None
    return class_counts(xml) if xml else None
