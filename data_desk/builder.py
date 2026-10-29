"""Data desk: fetch, standardise, convert, check. Produces CompanyData for the engine.

The only module in data_desk that does I/O (through Services). Everything it calls is pure and tested
separately; this module is exercised by offline tests with a seeded cache and by live tests.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone

from core.cache import CacheMiss
from core.http import DataSourceError
from data_desk import checks, lineage
from data_desk.adr import adr_ratio, implied_ratio
from data_desk.fmp_statements import annual_values, ltm_from_quarters
from data_desk.fx import FxRates, FxSeries, to_usd
from data_desk.standardise import AMBIGUOUS_DEBT, standardise
from data_desk.xbrl import extract
from datasources.fred import FX_SERIES
from engine.analysis import Analysis, analyse
from engine.flags import AMBER, INFO, Flag, sort_flags
from engine.model import Historicals
from engine.values import MILLIONS, PER_SHARE, SHARES_M, Value, calc


class DataDeskError(Exception):
    """The company cannot be processed at all (e.g. ticker unknown, no financial data)."""


@dataclass
class Profile:
    ticker: str
    name: str
    cik: int
    sic: str
    sic_description: str
    fiscal_year_end: str  # MMDD
    exchange: str
    entity_type: str
    reporting_currency: str
    taxonomy: str
    foreign_filer: bool
    tickers: list[str]
    country: str | None = None
    predecessor_cik: int | None = None  # successor issuer: annual history and annual reports are under this CIK

    @property
    def statements_cik(self) -> int:
        return getattr(self, "predecessor_cik", None) or self.cik


@dataclass
class Market:
    price: Value | None
    shares: Value | None             # ordinary shares (millions) used for market cap
    adr_ratio: float
    adr_source: str
    market_cap: Value | None         # computed, US$m
    provider_market_cap: Value | None  # US$m
    beta: Value | None
    notes: list[str] = field(default_factory=list)


@dataclass
class CompanyData:
    profile: Profile
    historicals: Historicals          # reporting currency
    historicals_usd: Historicals | None
    analysis: Analysis
    market: Market
    flags: list[Flag]
    earnings_history: list[dict]
    built_at: str
    steps: list[str] = field(default_factory=list)  # human-readable log for the progress panel

    @property
    def hard_stops(self) -> list[Flag]:
        return [f for f in self.flags if f.is_hard_stop]


def _safe(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except (DataSourceError, CacheMiss):
        return None


def _fx_rates(svc, currency: str) -> FxRates | None:
    if currency not in FX_SERIES:
        return None
    series_id, usd_per_unit = FX_SERIES[currency]
    c = _safe(svc.fred.series, series_id, start="2008-01-01")
    if c is None:
        return None
    return FxRates({currency: FxSeries(currency, series_id, usd_per_unit, tuple(map(tuple, c.payload)),
                                       c.fetched_at_iso)})


def build_company_data(ticker: str, svc, today: date | None = None, kpis: dict | None = None,
                       progress=None) -> CompanyData:
    """Assemble everything the engine needs for `ticker`. `progress(msg)` receives step updates."""
    today = today or date.today()
    say = progress or (lambda msg: None)
    steps: list[str] = []
    flags: list[Flag] = []

    def log(msg: str) -> None:
        steps.append(msg)
        say(msg)

    ticker = ticker.upper().strip()
    cik = svc.edgar.cik_for(ticker)
    if cik is None:
        raise DataDeskError(f"{ticker} is not in the SEC company list.")
    log("Fetching SEC filings list")
    sub = svc.edgar.submissions(cik).payload
    log("Fetching XBRL financial statements (companyfacts)")
    facts = svc.edgar.companyfacts(cik)
    payload, pred = facts.payload, None
    if lineage.annual_fact_count(payload) == 0:  # e.g. a new holding company (successor issuer) with no 10-K yet
        pred, how = lineage.find_predecessor(svc, cik, sub)
        if pred:
            log(f"New registrant: reading the predecessor's history (CIK {pred})")
            merged, check = lineage.merge_facts(payload, svc.edgar.companyfacts(pred).payload, pred)
            if merged is None:
                raise DataDeskError(f"{ticker}'s registrant (CIK {cik}) is a successor issuer of CIK {pred} ({how}), "
                                    f"but their reported figures do not agree: {check}.")
            payload = merged
            flags.append(Flag(INFO, "history_stitched", "History joined across two SEC registrants",
                              f"{sub.get('name', ticker)} (CIK {cik}) became the registrant through a holding-company "
                              f"reorganisation; annual history comes from the predecessor (CIK {pred}). Found via "
                              f"{how}. {check}.", None, {"predecessor_cik": pred}))
    h = standardise(extract(payload, facts.fetched_at_iso))
    if not h.periods:
        raise DataDeskError(f"No annual financial statements found in SEC XBRL data for {ticker}.")
    log(f"Extracted {len(h.fy_labels)} fiscal years ({h.fy_labels[0]}-{h.fy_labels[-1]})"
        + (f" + {h.ltm.label}" if h.ltm else ""))

    tickers_row = next((r for r in svc.edgar.company_tickers().payload if r["ticker"] == ticker), {})
    profile = Profile(
        ticker=ticker, name=sub.get("name", ticker), cik=cik, sic=str(sub.get("sic") or ""),
        sic_description=sub.get("sicDescription") or "", fiscal_year_end=sub.get("fiscalYearEnd") or "",
        exchange=tickers_row.get("exchange", ""), entity_type=sub.get("entityType") or "",
        reporting_currency=h.currency, taxonomy=h.taxonomy,
        foreign_filer=any(f in {"20-F", "40-F"} for f in sub["filings"]["recent"]["form"][:200]),
        tickers=list(sub.get("tickers") or [ticker]),
        country=(sub.get("addresses", {}).get("business", {}) or {}).get("stateOrCountryDescription"),
        predecessor_cik=pred,
    )

    # --- LTM fallback from FMP quarters (foreign filers have no interim XBRL) -----------------------
    annual = svc.edgar.filings(profile.statements_cik, forms={"10-K", "20-F", "40-F"})
    if annual and annual[0].report_date:
        newest = date.fromisoformat(annual[0].report_date)
        last_fy_end = [p for p in h.periods if p.kind == "FY"][-1].end
        if (newest - last_fy_end).days > 30:
            flags.append(Flag(AMBER, "newer_filing_not_in_xbrl", "Latest annual report not yet in XBRL data",
                              f"{annual[0].form} for the period ending {annual[0].report_date} was filed on "
                              f"{annual[0].filing_date}, but SEC's XBRL data stops at {h.fy_labels[-1]}. Figures use "
                              f"{h.fy_labels[-1]} until EDGAR processes the new filing.", None,
                              {"filed": annual[0].filing_date}))
    interim_failed = any("could not be built" in n for n in h.notes)
    if h.ltm is None and interim_failed:
        flags.append(Flag(AMBER, "ltm_failed", "LTM could not be built", " ".join(h.notes), None, {}))
    if h.ltm is None and profile.foreign_filer:
        last_end = h.periods[-1].end
        q = {k: _safe(svc.fmp.call, k, ticker) for k in ("income_statement_q", "cash_flow_q", "balance_sheet_q")}
        if all(q.values()):
            rep_ccy = (q["income_statement_q"].payload or [{}])[0].get("reportedCurrency")
            if rep_ccy and rep_ccy != h.currency:
                flags.append(Flag(INFO, "ltm_currency", "LTM fallback skipped",
                                  f"FMP quarterly data is in {rep_ccy}, filings are in {h.currency}; LTM not built.",
                                  None, {}))
            else:
                period, vals = ltm_from_quarters(q["income_statement_q"].payload, q["cash_flow_q"].payload,
                                                 q["balance_sheet_q"].payload, last_end, h.currency,
                                                 q["income_statement_q"].fetched_at_iso)
                if period:
                    h.periods.append(period)
                    for line, v in vals.items():
                        h.lines.setdefault(line, {})[period.label] = v
                    h = standardise(h)
                    flags.append(Flag(AMBER, "ltm_from_fmp", "LTM built from FMP quarterly data",
                                      f"No interim XBRL in EDGAR for {ticker}; {period.label} uses the last four FMP "
                                      f"quarters (balance sheet from the latest FMP quarter).", period.label, {}))
                    log(f"Built {period.label} from FMP quarterly statements")
        else:
            flags.append(Flag(AMBER, "ltm_unavailable", "No LTM figures",
                              f"No interim XBRL in EDGAR and FMP quarterly statements are unavailable for {ticker} on "
                              f"the current plan. LTM equals {h.fy_labels[-1]}.", None, {}))

    # --- FX -----------------------------------------------------------------------------------------
    flags += checks.currency_mismatch(h.currency)
    h_usd = h
    fx = None
    if h.currency != "USD":
        log(f"Converting {h.currency} to US$ with FRED rates")
        fx = _fx_rates(svc, h.currency)
        if fx is None:
            h_usd = None
            flags.append(Flag(AMBER, "fx_unavailable", "No FX rates",
                              f"No FRED series for {h.currency}; values stay in {h.currency}.", None, {}))
        else:
            h_usd, problems = to_usd(h, fx)
            for msg in problems[:3]:
                flags.append(Flag(AMBER, "fx_gap", "FX rate missing", msg, None, {}))

    # --- market data ----------------------------------------------------------------------------------
    log("Fetching price, market cap and beta")
    q = svc.market.quote(ticker)
    price = Value(q.data["price"], "USD", PER_SHARE, q.data.get("as_of") or "latest", q.source,
                  fetched_at=q.fetched_at, note="; ".join(q.notes) or None) if q.available else None
    shares = h.dei_shares
    last_fy = h.fy_labels[-1]
    if shares is None or shares.value is None:
        for line, p in (("shares_outstanding", h.ltm.label if h.ltm else last_fy), ("shares_outstanding", last_fy),
                        ("shares_basic_weighted", h.ltm.label if h.ltm else last_fy),
                        ("shares_basic_weighted", last_fy)):
            v = h.get(line, p)
            if v and v.value:
                shares = v.with_note("cover-page share count not tagged; using " + line.replace("_", " "))
                break
    ratio, ratio_src = adr_ratio(ticker)
    mcap = None
    if price and shares and shares.value:
        r = Value(ratio, None, "ratio", "current", ratio_src)
        mcap = calc(lambda p, s, k: p * s / k, "price x ordinary shares / ADR ratio", "current", MILLIONS, "USD",
                    price=price, shares=shares, adr_ratio=r)
    mc = svc.market.market_cap(ticker)
    provider = None
    if mc.available:
        val, ccy = mc.data["market_cap"] / 1e6, mc.data.get("currency") or "USD"
        provider = Value(val, ccy, MILLIONS, mc.data.get("as_of") or "latest", mc.source, fetched_at=mc.fetched_at,
                         note=f"listing {mc.data.get('listing')}")
        if ccy != "USD":
            fx_now = fx if (fx and ccy == h.currency) else _fx_rates(svc, ccy)
            rate = fx_now.at(ccy, today, "spot", max_gap_days=10) if fx_now else None
            provider = calc(lambda m, k: m * k, f"{mc.source} market cap ({ccy}) x latest US$/{ccy}", "current",
                            MILLIONS, "USD", market_cap=provider, rate=rate) if rate else None
    beta_r = svc.market.beta(ticker)
    beta = Value(beta_r.data["beta"], None, "ratio", "latest", beta_r.source, fetched_at=beta_r.fetched_at) \
        if beta_r.available else None
    detail = (f"Shares {shares.value:,.1f}m ({shares.tag or shares.source}, {shares.period}); ADR ratio {ratio:g} "
              f"({ratio_src}).") if shares and shares.value else "share count unavailable."
    point_in_time = bool(shares and shares.tag and shares.tag.split(":")[-1] in (
        "EntityCommonStockSharesOutstanding", "CommonStockSharesOutstanding", "NumberOfSharesOutstanding"))
    shares_date = (shares.period.split()[-1] if shares and shares.period else "")
    if point_in_time and len(shares_date) == 10 and (today - date.fromisoformat(shares_date)).days > checks.STALE_DAYS:
        point_in_time = False  # a share count this old cannot support a hard stop (buybacks/issuance since)
        detail += f" The share count is dated {shares_date}, over {checks.STALE_DAYS} days ago."
    flags += checks.market_cap(mcap.value if mcap else None, provider.value if provider else None,
                               mc.source or "provider", detail, point_in_time)
    if mcap and provider and mcap.value and price and shares:
        implied = implied_ratio(shares.value, price.value, provider.value)
        if implied and abs(implied / ratio - 1) > 0.10 and abs(implied - 1) > 0.10:
            flags.append(Flag(AMBER, "adr_ratio_check", "ADR ratio may be wrong",
                              f"Shares x price vs provider market cap implies {implied:.2f} ordinary shares per US "
                              f"share; the ratio used is {ratio:g} ({ratio_src}).", None, {"implied": implied}))
    market = Market(price, shares, ratio, ratio_src, mcap, provider, beta)

    # --- cross-check EDGAR vs FMP (latest fiscal year) -----------------------------------------------------
    st = {k: _safe(svc.fmp.call, k, ticker) for k in ("income_statement", "balance_sheet", "cash_flow")}
    fmp_ccy = (st["income_statement"].payload or [{}])[0].get("reportedCurrency") if st["income_statement"] else None
    if all(st.values()) and fmp_ccy not in (None, h.currency):
        flags.append(Flag(INFO, "xsource_currency", "EDGAR vs FMP cross-check not run",
                          f"FMP reports {ticker} in {fmp_ccy}; the filings are in {h.currency}.", None, {}))
    elif all(st.values()):
        fmp = annual_values(st["income_statement"].payload, st["balance_sheet"].payload, st["cash_flow"].payload,
                            h.periods[[p.label for p in h.periods].index(last_fy)].end)
        edgar = {"revenue": h.v("revenue", last_fy), "net_income": h.v("net_income_attributable", last_fy),
                 "cash": h.v("cash", last_fy), "shares": h.v("shares_diluted_weighted", last_fy)}
        other = {"revenue": fmp["revenue"], "net_income": fmp["net_income_attributable"], "cash": fmp["cash"],
                 "shares": fmp["shares_diluted_weighted"]}
        flags += checks.cross_source(edgar, other, "FMP", last_fy)
        # FMP's totalDebt includes lease liabilities, so compare like with like (no picking the closer figure)
        flags += checks.cross_source({"debt incl. leases": h.v("total_debt_incl_leases", last_fy)},
                                     {"debt incl. leases": fmp["fmp_total_debt"]}, "FMP", last_fy)
        log("Cross-checked EDGAR against FMP")
    else:
        flags.append(Flag(INFO, "xsource_unavailable", "EDGAR vs FMP cross-check not run",
                          f"FMP annual statements are unavailable for {ticker} on the current plan.", None, {}))

    # --- statement checks and corporate flags ------------------------------------------------------------
    valuation_periods = [last_fy] + ([h.ltm.label] if h.ltm else [])
    flags += checks.balance_sheet(h, valuation_periods)
    flags += checks.missing_key_lines(h, valuation_periods)
    flags += checks.ambiguous_debt(h, valuation_periods, AMBIGUOUS_DEBT)
    flags += checks.statement_sums(h)
    flags += checks.cash_flow_tie(h)
    flags += checks.net_income_vs_operating(h)
    flags += checks.negative_fcf(h)
    flags += checks.convertible_debt(h.convertible_evidence)
    if h.dei_shares and h.dei_shares.note and "share classes" in h.dei_shares.note:
        flags += checks.multiple_share_classes(int(h.dei_shares.note.split()[2]), h.dei_shares.note)
    for name, series in (kpis or {}).items():
        flags += checks.kpi_divergence(h, name, series)
    latest_filed, latest_form = None, None
    if h.ltm:
        v = h.get("revenue", h.ltm.label) or h.get("cfo", h.ltm.label)
        for x in ([v] + list(v.inputs) if v else []):
            if x.filing:
                latest_form, _, rest = x.filing.partition(" filed ")
                latest_filed = rest.split(" ")[0]
    if latest_filed is None and h.latest_annual_filing:
        latest_filed, latest_form = h.latest_annual_filing["filed"], h.latest_annual_filing["form"]
    flags += checks.filing_age(latest_filed, latest_form, today)

    log("Running financial analysis")
    eh = svc.market.earnings_history(ticker)
    earnings = eh.data if eh.available else []
    analysis = analyse(h, earnings)
    log("Data checks complete")
    return CompanyData(profile, h, h_usd, analysis, market, sort_flags(flags), earnings,
                       datetime.now(timezone.utc).isoformat(timespec="seconds"), steps)


__all__ = ["build_company_data", "CompanyData", "DataDeskError", "Profile", "Market", "SHARES_M"]
