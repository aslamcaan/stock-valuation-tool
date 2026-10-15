"""Data desk: comparable-company candidates and their metrics (from each peer's own SEC filings).

Candidates = FMP peers + Finnhub peers, kept only if they are SEC-registered and listed on a US exchange.
Each peer gets the same extraction as the company (XBRL -> standardise -> US$ -> analysis), so multiples are
computed on consistent definitions.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from core.cache import CacheMiss
from core.http import DataSourceError
from datetime import date

from data_desk.adr import adr_ratio
from data_desk.builder import _fx_rates
from data_desk.fx import to_usd
from data_desk.standardise import standardise
from data_desk.xbrl import extract
from datasources.search import US_EXCHANGES
from engine.analysis import analyse
from engine.comps import CompanyMetrics, earnings_distorted
from engine.model import Historicals

MAX_CANDIDATES = 15


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
        source=source)


def next_fy_eps(svc, ticker: str, after_iso: str) -> float | None:
    r = svc.market.analyst_estimates(ticker)
    if not r.available:
        return None
    rows = sorted((x for x in r.data if x.get("date", "")[:10] > after_iso and x.get("epsAvg") is not None
                   and (x.get("numAnalystsEps") or 0) >= 3), key=lambda x: x["date"])
    return float(rows[0]["epsAvg"]) if rows else None


def peer_metrics(svc, ticker: str, sec_rows: dict) -> tuple[CompanyMetrics | None, str | None]:
    row = sec_rows.get(ticker)
    if row is None:
        return None, f"{ticker}: not an SEC-registered US listing"
    try:
        sub = svc.edgar.submissions(int(row["cik"])).payload
        facts = svc.edgar.companyfacts(int(row["cik"]))
    except (DataSourceError, CacheMiss) as exc:
        return None, f"{ticker}: SEC data unavailable ({str(exc)[:80]})"
    h = standardise(extract(facts.payload, facts.fetched_at_iso))
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
        mc = svc.market.market_cap(ticker)
        if mc.available and (mc.data.get("currency") or "USD") == "USD":
            mcap, mc_src = mc.data["market_cap"] / 1e6, mc.source
    if mcap is None:
        return None, f"{ticker}: market cap unavailable"
    # forward EPS only for US$ reporters with ordinary shares listed (estimates are in the reporting currency)
    eps = _ok(next_fy_eps, svc, ticker, date.today().isoformat()) if reporting_ccy == "USD" and ratio == 1 else None
    return metrics_from(h, analysis, ticker=ticker, name=row["name"], sic=str(sub.get("sic") or ""),
                        market_cap=mcap, price=price, forward_eps=eps,
                        source=f"SEC XBRL ({latest_period(h)}); market cap {mc_src}"), None


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
    return out[:MAX_CANDIDATES], rows


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
