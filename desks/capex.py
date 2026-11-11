"""AI capex tracker data (no AI): for each hyperscaler, the latest forward-looking capex sentences from its newest earnings
release (8-K Item 2.02 exhibits) and, failing that, its newest quarterly or annual report: verbatim, with the filing
date and link. A company that gives its capex outlook only on the call shows as not found, never as a guess."""
from __future__ import annotations

from datetime import date


from core.http import DataSourceError, cache_key, get
from datasources.edgar import SOURCE, _LIMITER, Filing
from engine.capex import HYPERSCALERS, STALE_DAYS, age_days, capex_statements


def _filing(f: dict) -> Filing:
    acc = f["url"].split("/")[-2]
    return Filing(form=f["form"], accession=f"{acc[:10]}-{acc[10:12]}-{acc[12:]}", filing_date=f["filing_date"],
                  report_date="", primary_document=f["url"].split("/")[-1], description="")


def _text(svc, url: str) -> str:
    return svc.edgar.cache.get_or_fetch(
        "filings", cache_key(url),
        lambda: get(SOURCE, url, headers=svc.edgar._headers(), limiter=_LIMITER, timeout=60).text).payload


def _documents(svc, cik: int, f: dict) -> list[tuple[str, str]]:
    """(url, text) to search: an earnings release's exhibit 99 files, or a periodic report's primary document."""
    if f["form"] != "8-K":
        return [(f["url"], _text(svc, f["url"]))]
    acc = f["url"].split("/")[-2]
    out = []
    for d in svc.edgar.filing_documents(cik, _filing(f)):
        name = d.get("name", "")
        if "99" in name and name.lower().endswith((".htm", ".html", ".txt")):
            url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc}/{name}"
            out.append((url, _text(svc, url)))
    return out


def _newest(filings: list[dict], kind: str) -> dict | None:
    """The newest earnings release (8-K Item 2.02) or periodic report (10-Q, 10-K); filings come newest first."""
    for x in filings:
        if kind == "8-K" and x["form"] == "8-K" and "2.02" in x["items"]:
            return x
        if kind == "periodic" and x["form"] in ("10-Q", "10-K"):
            return x
    return None


def company_capex(svc, ticker: str, today: date) -> dict:
    row = {"ticker": ticker, "statements": [], "notes": []}
    try:
        cik = svc.edgar.cik_for(ticker)
        if cik is None:
            raise DataSourceError("SEC EDGAR", f"no CIK for {ticker}")
        filings, _ = svc.edgar.recent_filings_fresh(cik, {"8-K", "10-Q", "10-K"})
    except Exception as exc:  # noqa: BLE001
        row["notes"].append(f"Filings unavailable: {type(exc).__name__}.")
        return row
    for kind in ("8-K", "periodic"):
        # only the newest filing of each kind is read: an older one would be stale guidance
        f = _newest(filings, kind)
        if f is None:
            continue
        try:
            docs = _documents(svc, cik, f)
        except Exception as exc:  # noqa: BLE001
            row["notes"].append(f"{f['form']} of {f['filing_date']} could not be read ({type(exc).__name__}).")
            continue
        found = [(url, s) for url, raw in docs for s in capex_statements(raw)]
        for url, s in found[:2]:
            age = age_days(f["filing_date"], today)
            row["statements"].append({"quote": s, "form": f["form"], "filed": f["filing_date"], "url": url,
                                      "age_days": age, "stale": age > STALE_DAYS})
        if found:
            break
    if not row["statements"]:
        row["notes"].append("No forward-looking capex sentence with a dollar figure was found in the latest earnings "
                            "release or periodic report (some companies give it only on the call).")
    return row


def capex_tracker(svc, today: date | None = None) -> list[dict]:
    today = today or date.today()
    return [company_capex(svc, t, today) for t in HYPERSCALERS]
