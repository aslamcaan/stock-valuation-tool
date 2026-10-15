"""Data desk: assemble EngineInputs (every input a sourced Value) from CompanyData and the data clients."""
from __future__ import annotations

from datetime import date

from core.cache import CacheMiss
from core.http import DataSourceError
from data_desk.builder import CompanyData
from engine.forecast import ConsensusYear
from engine.values import RATIO, Value
from engine.valuation import EngineInputs, IndustryData

# FMP geographic segment labels -> Damodaran country (exact) or region (regional weighted average)
GEO_MAP = [
    (("united states", "u.s.", "domestic", "usa"), "country", "United States"),
    (("north america",), "region", "North America"),
    (("americas",), "region", "North America"),
    (("canada",), "country", "Canada"),
    (("latin america", "south america"), "region", "Central and South America"),
    (("greater china", "china", "hong kong", "taiwan"), "country", "China"),
    (("japan",), "country", "Japan"),
    (("korea",), "country", "Korea"),
    (("india",), "country", "India"),
    (("rest of asia", "asia pacific", "asia", "apac"), "region", "Asia"),
    (("europe", "emea", "united kingdom", "germany", "france"), "region", "Western Europe"),
    (("middle east",), "region", "Middle East"),
    (("africa",), "region", "Africa"),
    (("australia",), "region", "Australia & New Zealand"),
]
INDUSTRY_REGION = {"United States": "us", "Emerging Markets": "emerging"}


class InputsError(Exception):
    pass


def _try(fn, *a, **k):
    try:
        return fn(*a, **k)
    except (DataSourceError, CacheMiss, KeyError, StopIteration, ValueError):
        return None


def _geo_target(label: str) -> tuple[str, str] | None:
    lab = label.lower()
    for keys, kind, name in GEO_MAP:
        if any(k in lab for k in keys):
            return kind, name
    return None


def country_risk_premium(svc, ticker: str, domicile: str | None, broad_group: str | None) -> Value:
    """Revenue-weighted CRP relative to the US (the ERP used is the US implied premium)."""
    table, as_of, c = svc.damodaran.country_risk()
    regions, _ = svc.damodaran.regional_crp()
    us = table["United States"]["crp"]

    def rel(x: float) -> float:
        return max(0.0, x - us)

    geo = _try(svc.fmp.call, "revenue_geography", ticker)
    rows = geo.payload if geo else None
    if rows:
        latest = max(rows, key=lambda r: r.get("date", ""))
        data = {k: float(v) for k, v in (latest.get("data") or {}).items() if v and float(v) > 0}
        total = sum(data.values())
        parts, unmapped = [], 0.0
        for label, rev in data.items():
            t = _geo_target(label)
            if t is None:
                unmapped += rev
                continue
            kind, name = t
            crp = table.get(name, {}).get("crp") if kind == "country" else regions.get(name)
            if crp is None:
                unmapped += rev
                continue
            parts.append((label, rev / total, rel(crp), f"{kind} {name}"))
        if parts and unmapped / total < 0.25:
            mapped = sum(w for _, w, _, _ in parts)
            value = sum(w * x for _, w, x, _ in parts) / mapped
            detail = "; ".join(f"{lab} {w:.0%} -> {how} CRP {x:.2%}" for lab, w, x, how in parts)
            return Value(value, None, RATIO, f"FY{latest.get('fiscalYear')}", "FMP revenue geography x Damodaran CRP",
                         fetched_at=geo.fetched_at_iso, note=f"relative to US CRP {us:.2%}. {detail}"
                         + (f"; {unmapped / total:.0%} of revenue unmapped" if unmapped else ""))
    if domicile and domicile in table:
        rec = table[domicile]
        if broad_group == "Emerging Markets" and rec["region"] in regions and regions[rec["region"]] > rec["crp"]:
            x = rel(regions[rec["region"]])
            return Value(x, None, RATIO, as_of, "Damodaran regional CRP",
                         note=f"revenue geography unavailable; {domicile} is an emerging-markets company, so the "
                              f"GDP-weighted {rec['region']} average CRP is used as a proxy (relative to US). "
                              f"The research desk refines this from the annual report's geographic split.")
        return Value(rel(rec["crp"]), None, RATIO, as_of, "Damodaran country CRP",
                     note=f"revenue geography unavailable; domicile {domicile} used (relative to US CRP {us:.2%})")
    return Value(0.0, None, RATIO, as_of, "assumption", note="no geography or domicile: no country risk premium")


def consensus_rows(svc, ticker: str, currency: str) -> tuple[list[ConsensusYear], str | None]:
    r = svc.market.analyst_estimates(ticker)
    if not r.available:
        return [], "; ".join(r.notes)
    if currency != "USD":
        return [], f"consensus not used: filings are in {currency} and FMP estimates may be in another currency"
    out = []
    for row in r.data:
        try:
            out.append(ConsensusYear(date.fromisoformat(row["date"][:10]), row.get("revenueAvg", 0) / 1e6,
                                     (row.get("revenueLow") or 0) / 1e6, (row.get("revenueHigh") or 0) / 1e6,
                                     (row["ebitAvg"] / 1e6) if row.get("ebitAvg") is not None else None,
                                     int(row.get("numAnalystsRevenue") or 0), "FMP analyst estimates", r.fetched_at))
        except (KeyError, ValueError, TypeError):
            continue
    return out, None


def build_engine_inputs(cd: CompanyData, svc, valuation_date: date | None = None,
                        overrides: dict | None = None) -> tuple[EngineInputs, list[str]]:
    notes: list[str] = []
    h = cd.historicals_usd
    if h is None:
        raise InputsError(f"Figures could not be converted to US$ (no FX rate for {cd.historicals.currency}).")
    m = cd.market
    if m.price is None or m.shares is None or m.market_cap is None:
        raise InputsError("Price or share count unavailable, so the company cannot be valued.")
    p = cd.profile

    d, rf_raw, c = svc.fred.latest("DGS10")
    rf = Value(rf_raw / 100, None, RATIO, d, "FRED DGS10", tag="DGS10", fetched_at=c.fetched_at_iso,
               note="10-year Treasury constant maturity")
    e = svc.damodaran.implied_erp()
    erp = Value(e.value, None, RATIO, e.as_of, "Damodaran implied ERP", tag=e.file, fetched_at=e.fetched_at,
                note=e.detail)

    ind = svc.damodaran.industry_for(p.ticker, p.name, p.sic)
    region = INDUSTRY_REGION.get(ind.get("broad_group") or "", "global" if p.foreign_filer else "us")
    betas, b_asof, bc = svc.damodaran.industry_betas(region)
    margins, m_asof, mc = svc.damodaran.industry_margins(region)
    s2c, s_asof, sc = svc.damodaran.sales_to_capital("us" if region == "us" else "global")
    growth, g_asof, gc = svc.damodaran.industry_growth()
    name = ind["industry"]
    src = f"Damodaran {region.upper()} industry '{name}'"
    b = betas.get(name)
    unlev = Value(b["unlevered_beta_cash_adj"], None, RATIO, b_asof, src, tag="betas", fetched_at=bc.fetched_at_iso,
                  note=f"cash-adjusted unlevered beta, {b['firms']} firms; industry {ind['how']}") if b else None
    mg = margins.get(name)
    ind_margin = Value(mg["operating_margin"], None, RATIO, m_asof, src, tag="margins", fetched_at=mc.fetched_at_iso,
                       note="pre-tax unadjusted operating margin (industry aggregate)") \
        if mg and mg.get("operating_margin") is not None else None
    gr = growth.get(name)
    ind_growth = None
    if gr:
        x = gr["expected_revenue_growth"] if gr["expected_revenue_growth"] is not None else gr["revenue_cagr_5y"]
        if x is not None:
            ind_growth = Value(x, None, RATIO, g_asof, f"Damodaran US industry '{name}'", tag="histgr",
                               fetched_at=gc.fetched_at_iso,
                               note="expected revenue growth, next 2 years" if gr["expected_revenue_growth"] is not None
                               else "revenue CAGR, last 5 years")
    ind_s2c = Value(s2c[name], None, "x", s_asof, src, tag="capex", fetched_at=sc.fetched_at_iso,
                    note="sales / invested capital") if name in s2c else None
    industry = IndustryData(name, ind["how"], unlev, ind_margin, ind_growth, ind_s2c)

    domicile = ind.get("country") or ("United States" if not p.foreign_filer else None)
    crp = country_risk_premium(svc, p.ticker, domicile, ind.get("broad_group"))
    taxes, tc = svc.damodaran.country_tax_rates()
    tax_country = domicile if domicile in taxes else "United States"
    marginal_tax = Value(taxes[tax_country], None, RATIO, "2025", "Damodaran country tax rates",
                         fetched_at=tc.fetched_at_iso, note=f"marginal corporate tax rate, {tax_country}")
    large, _ = svc.damodaran.rating_table(True)
    small, _ = svc.damodaran.rating_table(False)
    consensus, cons_note = consensus_rows(svc, p.ticker, cd.historicals.currency)
    if cons_note:
        notes.append(cons_note)
    mcap = m.provider_market_cap if m.market_cap is None else m.market_cap
    return EngineInputs(
        ticker=p.ticker, name=p.name, sic=p.sic, valuation_date=valuation_date or date.today(), historicals=h,
        analysis=cd.analysis, price=m.price, basic_shares=m.shares, adr_ratio=m.adr_ratio, market_cap=mcap,
        risk_free=rf, erp=erp, beta_regression=m.beta, industry=industry, crp=crp, marginal_tax=marginal_tax,
        rating_table_large=large, rating_table_small=small, consensus=consensus, overrides=overrides or {}), notes


def crp_from_filing_geography(svc, geo: list[dict], source: str) -> Value | None:
    """CRP weighted by the annual report's own revenue split (research desk, verified quotes)."""
    table, as_of, c = svc.damodaran.country_risk()
    regions, _ = svc.damodaran.regional_crp()
    us = table["United States"]["crp"]
    rows = [(g["region"], g.get("revenue_millions") or g.get("share_of_revenue_pct")) for g in geo]
    rows = [(r, float(x)) for r, x in rows if x]
    total = sum(x for _, x in rows)
    if not rows or total <= 0:
        return None
    parts, unmapped = [], 0.0
    for label, x in rows:
        crp = None
        if label in table:
            crp, how = table[label]["crp"], f"country {label}"
        else:
            t = _geo_target(label)
            if t:
                kind, name = t
                crp = table.get(name, {}).get("crp") if kind == "country" else regions.get(name)
                how = f"{kind} {name}"
            else:
                for country in table:
                    if country.lower() in label.lower():
                        crp, how = table[country]["crp"], f"country {country}"
                        break
        if crp is None:
            unmapped += x
            continue
        parts.append((label, x / total, max(0.0, crp - us), how))
    if not parts or unmapped / total >= 0.25:
        return None
    mapped = sum(w for _, w, _, _ in parts)
    value = sum(w * x for _, w, x, _ in parts) / mapped
    return Value(value, None, RATIO, as_of, "annual report revenue geography x Damodaran CRP",
                 note=f"{source}; relative to US CRP {us:.2%}. " +
                      "; ".join(f"{lab} {w:.0%} -> {how} CRP {x:.2%}" for lab, w, x, how in parts))


def one_off_adjustments(research: dict, fy_labels: list[str]) -> dict[str, float]:
    """FY label -> amount to add back to operating income (charges added back, gains removed)."""
    out: dict[str, float] = {}
    for item in research.get("one_off_items", []):
        amt = item.get("amount_millions")
        fy = f"FY{str(item.get('fiscal_year', ''))[-4:]}"
        if not amt or not item.get("in_operating_income") or fy not in fy_labels:
            continue
        out[fy] = out.get(fy, 0.0) + (abs(amt) if item.get("effect") == "charge" else -abs(amt))
    return out
