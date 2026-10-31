"""Data desk: comparable-company candidates and their metrics (from each peer's own SEC filings).

Candidates = FMP peers + Finnhub peers, kept only if they are SEC-registered and listed on a US exchange, plus
US-listed filers in the same 2-digit SIC and of similar revenue found in SEC frames (no market-data plan needed).
Each peer gets the same extraction as the company (XBRL -> standardise -> US$ -> analysis), so multiples are
computed on consistent definitions.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from core.cache import CacheMiss
from core.http import DataSourceError
from datetime import date

from data_desk.adr import adr_ratio
from data_desk import lineage
from data_desk.builder import _fx_rates
from data_desk.fx import to_usd
from data_desk.standardise import standardise
from data_desk.xbrl import extract
from datasources.search import US_EXCHANGES
from engine.analysis import analyse
from engine.comps import CompanyMetrics, earnings_distorted
from engine.model import Historicals

MAX_CANDIDATES = 15
MAX_SEC_CANDIDATES = 8   # added from SEC frames on top of the provider peers
SEC_SCAN = 60            # nearest-by-revenue filers whose SIC is looked up
# US GAAP only: SEC's frames API does not serve the ifrs-full taxonomy (404), so 20-F filers come from the providers
REVENUE_CONCEPTS = (("us-gaap", "Revenues"), ("us-gaap", "RevenueFromContractWithCustomerExcludingAssessedTax"),
                    ("us-gaap", "SalesRevenueNet"))


def _ok(fn, *a, **k):
    try:
        return fn(*a, **k)
    except (DataSourceError, CacheMiss, KeyError, ValueError, IndexError, TypeError, ZeroDivisionError):
        return None


def latest_period(h: Historicals) -> str:
    return h.ltm.label if h.ltm and h.v("revenue", h.ltm.label) is not None else h.fy_labels[-1]


def metrics_from(h: Historicals, analysis, *, ticker: str, name: str, sic: str, market_cap: float | None,
                 price: float | None, forward_eps: float | None, source: str) -> CompanyMetrics:
    p = latest_period(h)
    last = h.fy_labels[-1]
    rg = analysis.m("revenue_growth", last)
    debt = h.v("debt_for_valuation", p) if h.v("debt_for_valuation", p) is not None else h.v("total_debt", p)
    if debt is None and h.v("total_assets", p) is not None:
        debt = 0.0  # balance sheet reported with no debt tagged: treated as debt-free, as in the DCF bridge
    ebitda = h.v("ebitda", p)
    return CompanyMetrics(
        ticker=ticker, name=name, sic=sic, market_cap=market_cap, price=price,
        revenue=h.v("revenue", p), ebitda=ebitda, fcf=h.v("fcf", p),
        net_income=h.v("net_income_attributable", p), forward_eps=forward_eps,
        debt=debt, cash=h.v("cash_and_investments", p), minority=h.v("minority_interest", p) or 0.0, period=p,
        operating_income=h.v("operating_income", p), preferred=h.v("preferred_equity", p) or 0.0,
        earnings_flagged=earnings_distorted(h.v("net_income_attributable", last), h.v("operating_income", last),
                                            h.v("revenue", last)),
        benchmarks={"revenue_growth": rg, "operating_margin": analysis.m("operating_margin", p),
                    "roic": analysis.m("roic", last), "fcf_margin": analysis.m("fcf_margin", p),
                    "net_debt_to_ebitda": analysis.m("net_debt_to_ebitda", p) if ebitda and ebitda > 0 else None},
        source=source, **financial_fields(h))


def financial_fields(h) -> dict:
    """Book, tangible book, earnings to common, FFO and an NOI proxy (latest fiscal year) for financial comps."""
    from engine.financials import common_equity, ffo, ni_common, noi_proxy, tangible_common_equity
    fy = h.fy_labels[-1] if h.fy_labels else None
    if fy is None:
        return {}
    return {"common_equity": common_equity(h, fy).value, "tangible_equity": tangible_common_equity(h, fy).value,
            "net_income_common": ni_common(h, fy).value, "ffo": ffo(h, fy).value, "noi": noi_proxy(h, fy).value}


def next_fy_eps(svc, ticker: str, after_iso: str) -> float | None:
    r = svc.market.analyst_estimates(ticker)
    if not r.available:
        return None
    rows = sorted((x for x in r.data if x.get("date", "")[:10] > after_iso and x.get("epsAvg") is not None
                   and (x.get("numAnalystsEps") or 0) >= 3), key=lambda x: x["date"])
    return float(rows[0]["epsAvg"]) if rows else None


def usd_market_cap(svc, mc, today: date | None = None) -> tuple[float | None, str | None]:
    """(US$ millions, source) from a market-cap lookup. A home-market listing's figure (e.g. KOF in MXN) is converted
    at FRED's latest daily rate, as the rest of the tool converts; None if there is no rate within ten days."""
    if not mc.available:
        return None, None
    ccy = mc.data.get("currency") or "USD"
    if ccy == "USD":
        return mc.data["market_cap"] / 1e6, mc.source
    fx = _fx_rates(svc, ccy)
    rate = fx.at(ccy, today or date.today(), "spot", max_gap_days=10) if fx else None
    if rate is None:
        return None, None
    return mc.data["market_cap"] / 1e6 * rate.value, f"{mc.source} ({ccy}) at {rate.source} ({rate.note})"


def peer_metrics(svc, ticker: str, sec_rows: dict) -> tuple[CompanyMetrics | None, str | None]:
    row = sec_rows.get(ticker)
    if row is None:
        return None, f"{ticker}: not an SEC-registered US listing"
    try:
        sub = svc.edgar.submissions(int(row["cik"])).payload
        facts = svc.edgar.companyfacts(int(row["cik"]))
    except (DataSourceError, CacheMiss) as exc:
        return None, f"{ticker}: SEC data unavailable ({str(exc)[:80]})"
    payload = facts.payload
    if lineage.annual_fact_count(payload) == 0:  # a successor issuer (e.g. XOM's new holding company): no 10-K yet
        pred, _ = lineage.find_predecessor(svc, int(row["cik"]), sub)
        if pred:
            try:
                merged, _ = lineage.merge_facts(payload, svc.edgar.companyfacts(pred).payload, pred)
            except (DataSourceError, CacheMiss):
                merged = None
            payload = merged or payload
    h = standardise(extract(payload, facts.fetched_at_iso))
    if not h.periods:
        return None, f"{ticker}: no XBRL financials"
    reporting_ccy = h.currency
    if h.currency != "USD":
        fx = _fx_rates(svc, h.currency)
        h2, problems = to_usd(h, fx) if fx else (None, ["no FX series"])
        if h2 is None:
            return None, f"{ticker}: reports in {h.currency} and could not be converted"
        h = h2
    analysis = analyse(h)
    ratio, _ = adr_ratio(ticker)
    q = svc.market.quote(ticker)
    price = q.data["price"] if q.available else None
    mcap, mc_src = None, None
    if price and h.dei_shares and h.dei_shares.value:
        mcap, mc_src = price * h.dei_shares.value / ratio, "price x SEC cover-page shares"  # same basis every run
    else:
        mcap, mc_src = usd_market_cap(svc, svc.market.market_cap(ticker))
    if mcap is None:
        return None, f"{ticker}: market cap unavailable"
    # forward EPS only for US$ reporters with ordinary shares listed (estimates are in the reporting currency)
    eps = _ok(next_fy_eps, svc, ticker, date.today().isoformat()) if reporting_ccy == "USD" and ratio == 1 else None
    return metrics_from(h, analysis, ticker=ticker, name=row["name"], sic=str(sub.get("sic") or ""),
                        market_cap=mcap, price=price, forward_eps=eps,
                        source=f"SEC XBRL ({latest_period(h)}); market cap {mc_src}"), None


def sec_revenues(svc, year: int) -> tuple[dict[str, float], str]:
    """{cik: annual revenue, US$} for every filer, from SEC frames: the latest calendar year, older years filling
    gaps, and the largest of the revenue lines a filer reports. Returns (revenues, frames used)."""
    out: dict[str, float] = {}
    used = []
    for y in (year - 2, year - 1):  # later years overwrite earlier ones
        got: dict[str, float] = {}
        for taxonomy, concept in REVENUE_CONCEPTS:
            frame = _ok(svc.edgar.frame, concept, f"CY{y}", taxonomy)
            for cik, val in (frame.payload if frame else {}).items():
                got[cik] = max(got.get(cik, 0.0), float(val))
            if frame:
                used.append(f"{concept} CY{y}")
        out.update(got)
    return out, ", ".join(used)


def sec_candidates(svc, ticker: str, rows: dict, exclude: set[str], year: int) -> tuple[list[str], str | None]:
    """US-listed companies in the same 2-digit SIC and 0.25x-4x the company's revenue, nearest in size first: the
    brief's peer rule applied to SEC's own data, so peers do not depend on a market-data plan."""
    import math
    own = rows.get(ticker.upper())
    if own is None:
        return [], None
    revenues, used = sec_revenues(svc, year)
    rev = revenues.get(str(own["cik"]))
    sub = _ok(svc.edgar.submissions, int(own["cik"]))
    sic = str((sub.payload if sub else {}).get("sic") or "")
    if not rev or rev <= 0 or len(sic) < 2:
        return [], None
    by_cik: dict[str, str] = {}
    for t, r in rows.items():  # one ticker per company (share classes share a CIK)
        by_cik.setdefault(str(r["cik"]), t)
    near = sorted((abs(math.log(revenues[c] / rev)), t) for c, t in by_cik.items()
                  if c != str(own["cik"]) and t not in exclude and revenues.get(c, 0) > 0
                  and 0.25 <= revenues[c] / rev <= 4)[:SEC_SCAN]

    def sic_of(t):
        s = _ok(svc.edgar.submissions, int(rows[t]["cik"]))
        return str((s.payload if s else {}).get("sic") or "")
    with ThreadPoolExecutor(max_workers=4) as pool:
        sics = list(pool.map(sic_of, [t for _, t in near]))
    picked = [t for (_, t), s in zip(near, sics) if s[:2] == sic[:2]][:MAX_SEC_CANDIDATES]
    return picked, f"SEC frames ({used}): same 2-digit SIC {sic[:2]}, 0.25x-4x revenue"


def candidate_tickers(svc, ticker: str) -> tuple[list[str], dict]:
    rows = {r["ticker"]: r for r in svc.edgar.company_tickers().payload if r.get("exchange") in US_EXCHANGES}
    cands: list[str] = []
    fmp = svc.market.peers(ticker)
    if fmp.available:
        cands += fmp.data
    fh = _ok(svc.finnhub.call, "peers", ticker)
    if fh is not None and isinstance(fh.payload, list):
        cands += fh.payload
    seen, out = set(), []
    for c in cands:
        c = str(c).upper()
        if c != ticker.upper() and c in rows and c not in seen:
            seen.add(c)
            out.append(c)
    out = out[:MAX_CANDIDATES]
    sec, _ = sec_candidates(svc, ticker, rows, set(out) | {ticker.upper()}, date.today().year)
    return out + sec, rows


def gather_peers(svc, ticker: str, progress=None) -> tuple[list[CompanyMetrics], list[str]]:
    """(candidate metrics, notes about candidates that were skipped)."""
    tickers, rows = candidate_tickers(svc, ticker)
    notes = [] if tickers else ["no US-listed peer candidates from FMP or Finnhub"]
    out: list[CompanyMetrics] = []
    with ThreadPoolExecutor(max_workers=4) as pool:
        for t, (m, why) in zip(tickers, pool.map(lambda t: peer_metrics(svc, t, rows), tickers)):
            if progress:
                progress(f"Peer {t}: {'ok' if m else why}")
            if m is not None:
                out.append(m)
            elif why:
                notes.append(why)
    return out, notes
