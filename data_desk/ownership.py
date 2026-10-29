"""Ownership and insider activity (code, no AI): insider transactions from SEC Form 4, major holders from SEC
Schedule 13D/13G, short interest from FINRA, institutional holders from FMP where the plan allows.

Every figure carries its filing or source and date. Open-market purchases (code P) and sales (code S) are the
signal; option exercises, grants and tax withholding are listed but not counted as buying or selling.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import date, timedelta

from core.cache import CacheMiss
from core.http import DataSourceError

FORM4_DAYS = 180
MAX_FORM4 = 60
MAX_13 = 40          # Schedule 13D/G reads per report (asset managers file hundreds on other companies)
INSTITUTIONAL_LAG = 45  # 13F filings are due 45 days after quarter end
HOLDER_YEARS = 3
CODES = {"P": "open-market purchase", "S": "open-market sale", "M": "option exercise", "A": "grant or award",
         "F": "shares withheld for tax", "G": "gift", "C": "conversion", "D": "disposed to the issuer",
         "J": "other", "X": "option exercise", "W": "inheritance"}
FORMS_4 = {"4", "4/A"}
FORMS_13 = {"SCHEDULE 13G", "SCHEDULE 13G/A", "SCHEDULE 13D", "SCHEDULE 13D/A"}
FORMS_13_OLD = {"SC 13G", "SC 13G/A", "SC 13D", "SC 13D/A"}


@dataclass
class InsiderTrade:
    filed: str
    date: str
    owner: str
    role: str
    code: str
    action: str
    shares: float
    price: float | None
    value: float | None        # shares x price, US$ (code)
    owned_after: float | None
    plan_10b5_1: bool
    url: str
    owner_cik: str = ""


@dataclass
class Holder:
    name: str
    form: str
    filed: str
    event_date: str
    shares: float | None
    percent: float | None      # as reported on the cover page
    url: str
    filer_cik: str = ""
    security: str = ""         # class of shares the percentage refers to


@dataclass
class Ownership:
    as_of: str
    trades: list[InsiderTrade] = field(default_factory=list)
    holders: list[Holder] = field(default_factory=list)
    short: list[dict] = field(default_factory=list)          # FINRA rows, oldest first, plus pct_of_shares
    institutional: list[dict] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    window_days: int = FORM4_DAYS       # days of Form 4 filings actually read (shorter when capped)
    institutional_period: str = ""      # e.g. "2026 Q2"

    def summary(self) -> dict:
        buys = [t for t in self.trades if t.code == "P"]
        sells = [t for t in self.trades if t.code == "S"]
        bv = sum(t.value or 0 for t in buys)
        sv = sum(t.value or 0 for t in sells)
        return {"window_days": getattr(self, "window_days", FORM4_DAYS), "buys": len(buys), "sells": len(sells), "buy_value": bv, "sell_value": sv,
                "net_value": bv - sv, "buyers": len({t.owner for t in buys}), "sellers": len({t.owner for t in sells}),
                "planned_sells": sum(t.plan_10b5_1 for t in sells)}


def _strip(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _find(el, path: str):
    """First descendant matching a '/'-separated path of local tag names (namespaces ignored)."""
    parts = path.split("/")
    nodes = [el]
    for part in parts:
        nxt = []
        for n in nodes:
            nxt += [c for c in n.iter() if c is not n and _strip(c.tag) == part]
        if not nxt:
            return None
        nodes = nxt[:1]
    return nodes[0]


def _text(el, path: str) -> str:
    n = _find(el, path) if el is not None else None
    if n is None:
        return ""
    v = _find(n, "value")
    return ((v.text if v is not None else n.text) or "").strip()


def _num(s: str) -> float | None:
    try:
        return float(s.replace(",", ""))
    except (ValueError, AttributeError):
        return None


def _cik(s: str) -> int | None:
    try:
        return int(s)
    except (TypeError, ValueError):
        return None


def issuer_cik(xml: str) -> int | None:
    """The company a Form 4 or Schedule 13D/G is ABOUT. A company's own filing feed also holds filings it made as
    an owner of other companies; those must not count as its own insiders or holders."""
    root = ET.fromstring(xml.encode("utf-8") if isinstance(xml, str) else xml)
    return _cik(_text(root, "issuer/issuerCik") or _text(root, "issuerInfo/issuerCik") or _text(root, "issuerCik"))


def parse_form4(xml: str, filed: str, url: str) -> list[InsiderTrade]:
    root = ET.fromstring(xml.encode("utf-8") if isinstance(xml, str) else xml)
    owners = []
    for ro in [c for c in root.iter() if _strip(c.tag) == "reportingOwner"]:
        name = _text(ro, "rptOwnerName")
        rel = _find(ro, "reportingOwnerRelationship")
        roles = []
        if rel is not None:
            if _text(rel, "isDirector") in ("1", "true"):
                roles.append("Director")
            if _text(rel, "isOfficer") in ("1", "true"):
                roles.append(_text(rel, "officerTitle") or "Officer")
            if _text(rel, "isTenPercentOwner") in ("1", "true"):
                roles.append("10% owner")
        owners.append((name, ", ".join(roles) or "Other", _text(ro, "rptOwnerCik")))
    owner, role = (" / ".join(o[0] for o in owners), " / ".join(dict.fromkeys(o[1] for o in owners))) \
        if owners else ("unknown", "")
    owner_cik = owners[0][2] if owners else ""
    plan = _text(root, "aff10b5One") in ("1", "true")
    out = []
    for tx in [c for c in root.iter() if _strip(c.tag) == "nonDerivativeTransaction"]:
        code = _text(tx, "transactionCoding/transactionCode")
        shares = _num(_text(tx, "transactionAmounts/transactionShares"))
        price = _num(_text(tx, "transactionAmounts/transactionPricePerShare"))
        if shares is None:
            continue
        out.append(InsiderTrade(filed, _text(tx, "transactionDate") or filed, owner, role, code,
                                CODES.get(code, f"code {code}"), shares, price if price else None,
                                shares * price if price else None,
                                _num(_text(tx, "postTransactionAmounts/sharesOwnedFollowingTransaction")), plan, url,
                                owner_cik))
    return out


def parse_13g(xml: str, form: str, filed: str, url: str) -> Holder | None:
    """The largest reporting person on a Schedule 13D/13G cover page (group filings list each member; 13G puts them
    under coverPageHeaderReportingPersonDetails, 13D under reportingPersonInfo)."""
    root = ET.fromstring(xml.encode("utf-8") if isinstance(xml, str) else xml)
    best = None
    filer = _text(root, "filerCredentials/cik")
    people = [c for c in root.iter() if _strip(c.tag) in ("coverPageHeaderReportingPersonDetails",
                                                          "reportingPersonInfo")]
    for p in people:
        name = _text(p, "reportingPersonName")
        shares = _num(_text(p, "reportingPersonBeneficiallyOwnedAggregateNumberOfShares")
                      or _text(p, "aggregateAmountOwned"))
        pct = _num(_text(p, "classPercent") or _text(p, "percentOfClass"))
        if name and (best is None or (shares or 0) > (best.shares or 0)):
            best = Holder(name, form, filed, "", shares, pct, url, filer)
    if best is not None:
        best.security = _text(root, "securitiesClassTitle")
        ev = _text(root, "eventDateRequiresFilingThisStatement") or _text(root, "dateOfEvent")
        if len(ev) == 10 and ev[2] == "/":  # MM/DD/YYYY
            ev = f"{ev[6:]}-{ev[:2]}-{ev[3:5]}"
        best.event_date = ev
    return best


def last_13f_quarter(today: date) -> tuple[int, int]:
    """The latest calendar quarter whose 13F filing deadline (45 days after quarter end) has passed."""
    y, q = today.year, (today.month - 1) // 3  # q = the last quarter that has ended (0 = Q4 of last year)
    for _ in range(3):
        if q == 0:
            y, q = y - 1, 4
        end = date(y, 3 * q, 31 if q in (1, 4) else 30)
        if (today - end).days >= INSTITUTIONAL_LAG:
            return y, q
        q -= 1
    return y, q


def build_ownership(svc, cik: int, ticker: str, us_shares: float | None, today: date | None = None) -> Ownership:
    """`us_shares` in millions of US-listed shares (ordinary shares / ADR ratio), for short interest as a % of
    shares. Each section is independent: a failure in one leaves the others and says why."""
    today = today or date.today()
    own = Ownership(as_of=today.isoformat())
    try:
        filings, _ = svc.edgar.recent_filings_fresh(cik, FORMS_4 | FORMS_13 | FORMS_13_OLD)
    except Exception as exc:
        filings = []
        own.notes.append(f"SEC filing list unavailable: {type(exc).__name__}: {exc}")
    for section in (_insiders, _holders, _short, _institutional):
        try:
            section(svc, own, filings, cik, ticker, us_shares, today)
        except Exception as exc:  # one source failing must not hide the others
            own.notes.append(f"{section.__name__.strip('_').capitalize()} section unavailable: "
                             f"{type(exc).__name__}: {exc}")
    return own


def _insiders(svc, own, filings, cik, ticker, us_shares, today):
    cutoff = (today - timedelta(days=FORM4_DAYS)).isoformat()
    f4 = [f for f in filings if f["form"] in FORMS_4 and f["filing_date"] >= cutoff]
    if not f4:
        own.notes.append(f"No Form 4 filings in the last {FORM4_DAYS} days (foreign private issuers are not "
                         "required to file them).")
        return
    if len(f4) > MAX_FORM4:
        f4 = f4[:MAX_FORM4]  # newest first
        own.window_days = (today - date.fromisoformat(f4[-1]["filing_date"])).days
        own.notes.append(f"Many Form 4 filings: the latest {MAX_FORM4} are read, covering the last "
                         f"{own.window_days} days rather than {FORM4_DAYS}.")
    bad = other = dupes = 0
    seen: set = set()
    for f in f4:  # newest first, so an amendment (4/A) is read before the original it restates
        try:
            xml = svc.edgar.raw_xml(f["url"]).payload
            if issuer_cik(xml) not in (None, int(cik)):
                other += 1  # filed by this company as an owner of another company
                continue
            for t in parse_form4(xml, f["filing_date"], f["url"]):
                key = (t.owner_cik or t.owner, t.date, t.code, t.shares, t.price)
                if key in seen:
                    dupes += 1
                    continue
                seen.add(key)
                own.trades.append(t)
        except (DataSourceError, CacheMiss, ET.ParseError):
            bad += 1
    if bad:
        own.notes.append(f"{bad} Form 4 filings could not be read.")
    if other:
        own.notes.append(f"{other} Form 4 filings in the company's feed concern other issuers (the company as an "
                         "owner) and are excluded.")
    if dupes:
        own.notes.append(f"{dupes} transactions repeated in amendments (Form 4/A) were counted once.")
    own.trades.sort(key=lambda t: t.date, reverse=True)


def _holders(svc, own, filings, cik, ticker, us_shares, today):
    since = (today - timedelta(days=365 * HOLDER_YEARS)).isoformat()
    f13 = [f for f in filings if f["form"] in FORMS_13 and f["filing_date"] >= since]
    if len(f13) > MAX_13:
        own.notes.append(f"{len(f13)} Schedule 13D/13G filings in the feed; the latest {MAX_13} are read.")
        f13 = f13[:MAX_13]
    latest: dict[str, Holder] = {}
    other = 0
    for f in f13:
        try:
            xml = svc.edgar.raw_xml(f["url"]).payload
            if issuer_cik(xml) not in (None, int(cik)):
                other += 1
                continue
            h = parse_13g(xml, f["form"], f["filing_date"], f["url"])
        except (DataSourceError, CacheMiss, ET.ParseError):
            continue
        key = (h.filer_cik or h.name, h.security.lower()) if h else None  # one row per filer and share class
        if h and (key not in latest or h.filed > latest[key].filed):  # the filer's latest filing stands
            latest[key] = h
    own.holders = sorted(latest.values(), key=lambda h: -(h.percent or 0))
    if other:
        own.notes.append(f"{other} Schedule 13D/13G filings in the company's feed are its own stakes in other "
                         "companies and are excluded.")
    old = [f for f in filings if f["form"] in FORMS_13_OLD and f["filing_date"] >= since]
    if old:
        own.notes.append(f"{len(old)} older Schedule 13D/13G filings (text format before the SEC's 2024 XML switch) "
                         "are not parsed; holders who have not filed since may be missing.")


def _short(svc, own, filings, cik, ticker, us_shares, today):
    if svc.finra is None:
        own.notes.append("Short interest not fetched: the FINRA client is not configured.")
        return
    try:
        rows = svc.finra.short_interest(ticker, today).payload
    except (DataSourceError, CacheMiss) as exc:
        own.notes.append(f"Short interest unavailable: {exc}")
        return
    for r in rows[-6:]:
        q = r.get("currentShortPositionQuantity")
        pct = q / (us_shares * 1e6) if q is not None and us_shares else None
        own.short.append({"settlement_date": r.get("settlementDate"), "short_shares": q,
                          "change_pct": (r.get("changePercent") or 0) / 100 if r.get("changePercent") is not None
                          else None, "days_to_cover": r.get("daysToCoverQuantity"), "pct_of_shares": pct,
                          "avg_daily_volume": r.get("averageDailyVolumeQuantity")})
    if not own.short:
        own.notes.append(f"FINRA reported no short interest for {ticker} in the last 120 days (share-class tickers "
                         "may be listed under another symbol).")


def _institutional(svc, own, filings, cik, ticker, us_shares, today):
    y, q = last_13f_quarter(today)
    try:
        inst = svc.fmp.call("institutional_ownership", ticker, year=y, quarter=q)
    except (DataSourceError, CacheMiss):
        own.notes.append("Institutional holders (13F) are not available on the current FMP plan; the major holders "
                         "above come from their own SEC filings.")
        return
    own.institutional = inst.payload if isinstance(inst.payload, list) else []
    own.institutional_period = f"{y} Q{q}"
    if not own.institutional:
        own.notes.append(f"FMP returned no institutional (13F) data for {y} Q{q}.")
