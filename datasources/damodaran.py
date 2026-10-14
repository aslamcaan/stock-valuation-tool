"""Damodaran datasets (pages.stern.nyu.edu/~adamodar). Published files only; no page scraping.

Files are downloaded as binaries, cached 30 days, and parsed into plain dicts.
"""
from __future__ import annotations

import io
import warnings
from dataclasses import dataclass
from datetime import datetime

import pandas as pd

from core.cache import Cache, Cached
from core.http import cache_key, get

SOURCE = "Damodaran"
BASE = "https://pages.stern.nyu.edu/~adamodar/pc/"
FILES = {
    "erp": "implprem/ERPbymonth.xlsx",
    "country": "datasets/ctryprem.xlsx",
    "betas_us": "datasets/betas.xls",
    "betas_global": "datasets/betaGlobal.xls",
    "betas_emerging": "datasets/betaemerg.xls",
    "margins_us": "datasets/margin.xls",
    "margins_global": "datasets/marginGlobal.xls",
    "margins_emerging": "datasets/marginemerg.xls",
    "industry_names": "datasets/indname.xls",
    "capex_us": "datasets/capex.xls",
    "capex_global": "datasets/capexGlobal.xls",
    "growth_us": "datasets/histgr.xls",
    "ratings": "ratings.xls",
}

_NAME_NOISE = {"inc", "corp", "corporation", "co", "company", "ltd", "limited", "holdings", "holding", "plc", "nv",
               "n", "v", "sa", "ag", "se", "the", "group", "class", "a", "de", "llc", "lp"}
US_EXCHANGE_PREFIXES = ("Nasdaq", "NYSE", "NYSEAM", "NYSEArca", "BATS", "Cboe")


def normalise_name(name: str) -> str:
    import re
    words = re.sub(r"[^a-z0-9 ]", " ", name.lower()).split()
    return " ".join(w for w in words if w not in _NAME_NOISE)


@dataclass(frozen=True)
class Sourced:
    """A Damodaran figure with where it came from."""
    value: float
    as_of: str  # dataset date
    file: str
    detail: str
    fetched_at: str


def _excel(raw: bytes, sheet: str) -> pd.DataFrame:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return pd.read_excel(io.BytesIO(raw), sheet_name=sheet, header=None)


def _date_str(v) -> str:
    return v.strftime("%Y-%m-%d") if isinstance(v, (datetime, pd.Timestamp)) else str(v)


def _table(df: pd.DataFrame, first_header: str) -> pd.DataFrame:
    """Slice out the table whose header row starts with `first_header`."""
    idx = next(i for i in range(len(df)) if str(df.iat[i, 0]).strip() == first_header)
    body = df.iloc[idx + 1:].copy()
    body.columns = [str(c).strip() for c in df.iloc[idx]]
    return body[body.iloc[:, 0].notna()].reset_index(drop=True)


class DamodaranClient:
    def __init__(self, cache: Cache):
        self.cache = cache

    def raw(self, name: str) -> Cached:
        url = BASE + FILES[name]
        return self.cache.get_or_fetch("damodaran", cache_key(url), lambda: get(SOURCE, url, timeout=60).content,
                                       binary=True)

    # --- implied equity risk premium ------------------------------------------------
    def implied_erp(self) -> Sourced:
        c = self.raw("erp")
        df = _excel(c.payload, "Last 12 months data")
        df = df[pd.to_datetime(df[0], errors="coerce", format="mixed").notna() & pd.to_numeric(df[3], errors="coerce").notna()]
        last = df.iloc[-1]
        return Sourced(float(last[3]), _date_str(last[0]), FILES["erp"],
                       f"Implied ERP (trailing 12m cash yield), start of month {_date_str(last[0])}",
                       c.fetched_at_iso)

    # --- country risk premiums --------------------------------------------------------
    def country_risk(self) -> tuple[dict[str, dict], str, Cached]:
        """{country: {region, rating, crp, total_erp}} using the rating-based CRP column."""
        c = self.raw("country")
        df = _excel(c.payload, "ERPs by country")
        as_of = _date_str(df.iat[1, 1])
        t = _table(df, "Country")
        out = {}
        for _, r in t.iterrows():
            crp = pd.to_numeric(r.iloc[5], errors="coerce")
            if pd.isna(crp):
                continue
            out[str(r.iloc[0]).strip()] = {"region": str(r.iloc[1]).strip(), "rating": str(r.iloc[2]).strip(),
                                           "crp": float(crp), "total_erp": float(r.iloc[4])}
        return out, as_of, c

    def regional_crp(self) -> tuple[dict[str, float], Cached]:
        """GDP-weighted regional average CRP (for disclosures given by region, e.g. 'Asia')."""
        c = self.raw("country")
        t = _table(_excel(c.payload, "Regional Weighted Averages"), "Country")
        t["Weight*CRP"] = pd.to_numeric(t["Weight*CRP"], errors="coerce")
        t = t[t["Region"].notna() & t["Weight*CRP"].notna()]
        return {str(k).strip(): float(v) for k, v in t.groupby("Region")["Weight*CRP"].sum().items()}, c

    # --- industry betas and margins -------------------------------------------------------
    def industry_betas(self, region: str = "us") -> tuple[dict[str, dict], str, Cached]:
        c = self.raw(f"betas_{region}")
        df = _excel(c.payload, "Industry Averages")
        as_of = _date_str(df.iat[0, 1])
        t = _table(df, "Industry Name")
        out = {}
        for _, r in t.iterrows():
            out[str(r["Industry Name"]).strip()] = {
                "firms": int(r["Number of firms"]),
                "beta": float(r["Beta"]),
                "de_ratio": float(r["D/E Ratio"]),
                "tax_rate": float(r["Effective Tax rate"]),
                "unlevered_beta": float(r["Unlevered beta"]),
                "cash_firm_value": float(r["Cash/Firm value"]),
                "unlevered_beta_cash_adj": float(r["Unlevered beta corrected for cash"]),
            }
        return out, as_of, c

    def industry_margins(self, region: str = "us") -> tuple[dict[str, dict], str, Cached]:
        c = self.raw(f"margins_{region}")
        df = _excel(c.payload, "Industry Averages")
        as_of = _date_str(df.iat[0, 1])
        t = _table(df, "Industry Name")
        cols = {
            "gross_margin": "Gross Margin", "net_margin": "Net Margin",
            "operating_margin": "Pre-tax Unadjusted Operating Margin",
            "operating_margin_lease_adj": "Pre-tax Lease adjusted Margin",
            "ebitda_margin": "EBITDA/Sales", "sbc_to_sales": "Stock-Based Compensation/Sales",
            "rnd_to_sales": "R&D/Sales",
        }
        out = {}
        for _, r in t.iterrows():
            row = {"firms": int(r["Number of firms"])}
            for k, col in cols.items():
                v = pd.to_numeric(r.get(col), errors="coerce")
                row[k] = None if pd.isna(v) else float(v)
            out[str(r["Industry Name"]).strip()] = row
        return out, as_of, c

    # --- industry classification (company -> Damodaran industry) ------------------------------------
    def industry_index(self) -> tuple[dict, Cached]:
        """Compact index parsed from indname.xls (cached as JSON): by US ticker, by name, by SIC."""
        raw = self.raw("industry_names")

        def build():
            df = pd.read_excel(io.BytesIO(raw.payload), sheet_name="By company name", header=0)
            by_ticker, by_name, sic_counts = {}, {}, {}
            for row in df.itertuples(index=False):
                name, exch_ticker, industry, sector, sic, country, broad, sub = row[:8]
                if not isinstance(exch_ticker, str) or not isinstance(industry, str):
                    continue
                exch, _, tick = exch_ticker.partition(":")
                rec = {"industry": industry, "sector": sector, "country": country, "broad_group": broad,
                       "sub_group": sub if isinstance(sub, str) else None, "listing": exch_ticker,
                       "name": str(name)}
                if exch.startswith(US_EXCHANGE_PREFIXES):
                    by_ticker.setdefault(tick.upper(), rec)
                key = normalise_name(str(name).split(" (")[0])
                by_name.setdefault(key, rec)
                if country == "United States" and not pd.isna(sic):
                    counts = sic_counts.setdefault(str(int(sic)), {})
                    counts[industry] = counts.get(industry, 0) + 1
            by_sic = {k: max(v, key=v.get) for k, v in sic_counts.items()}
            return {"by_ticker": by_ticker, "by_name": by_name, "by_sic": by_sic,
                    "fetched_at": raw.fetched_at_iso}

        key = cache_key(BASE + FILES["industry_names"]) + "#index-v1"
        return self.cache.get_or_fetch("damodaran", key, build).payload, raw

    def industry_for(self, ticker: str, company_name: str, sic: str) -> dict:
        """Damodaran industry for a company: by US ticker, then company name, then most common for its SIC."""
        idx, raw = self.industry_index()
        rec = idx["by_ticker"].get(ticker.upper())
        how = f"matched ticker {ticker.upper()}"
        if rec is None:
            rec = idx["by_name"].get(normalise_name(company_name))
            how = f"matched company name '{company_name}'"
        if rec is None and sic in idx["by_sic"]:
            rec = {"industry": idx["by_sic"][sic], "country": None, "broad_group": None, "listing": None}
            how = f"most common industry for US companies with SIC {sic}"
        if rec is None:
            rec = {"industry": "Total Market (without financials)", "country": None, "broad_group": None,
                   "listing": None}
            how = "no match: market average used"
        return {**rec, "how": how, "file": FILES["industry_names"], "fetched_at": idx["fetched_at"]}

    def sales_to_capital(self, region: str = "us") -> tuple[dict[str, float], str, Cached]:
        c = self.raw(f"capex_{region}")
        df = _excel(c.payload, "Industry Averages")
        as_of = _date_str(df.iat[0, 1])
        t = _table(df, "Industry Name")
        col = next(x for x in t.columns if x.startswith("Sales/"))
        out = {}
        for _, r in t.iterrows():
            v = pd.to_numeric(r[col], errors="coerce")
            if not pd.isna(v):
                out[str(r["Industry Name"]).strip()] = float(v)
        return out, as_of, c

    def industry_growth(self) -> tuple[dict[str, dict], str, Cached]:
        """US industry revenue CAGR (last 5 years) and expected revenue growth (next 2 years)."""
        c = self.raw("growth_us")
        df = _excel(c.payload, "Industry Averages")
        as_of = _date_str(df.iat[0, 1])
        t = _table(df, "Industry Name")
        cols = list(t.columns)
        rev_hist = next(x for x in cols if "Revenues" in x and "CAGR" in x)
        rev_exp = next((x for x in cols if "Revenues" in x and "Expected" in x), None)
        out = {}
        for _, r in t.iterrows():
            h = pd.to_numeric(r[rev_hist], errors="coerce")
            e = pd.to_numeric(r[rev_exp], errors="coerce") if rev_exp else float("nan")
            out[str(r["Industry Name"]).strip()] = {"revenue_cagr_5y": None if pd.isna(h) else float(h),
                                                    "expected_revenue_growth": None if pd.isna(e) else float(e)}
        return out, as_of, c

    def rating_table(self, large: bool = True) -> tuple[list[dict], Cached]:
        """Synthetic rating table: interest coverage bands -> rating and default spread."""
        c = self.raw("ratings")
        df = _excel(c.payload, "Start here Ratings sheet")
        start = 18 if large else 37
        rows = []
        for i in range(start, start + 15):
            lo, hi, rating, spread = (df.iat[i, j] for j in range(4))
            rows.append({"min": float(lo), "max": float(hi), "rating": str(rating), "spread": float(spread)})
        return rows, c

    def country_tax_rates(self) -> tuple[dict[str, float], Cached]:
        c = self.raw("country")
        df = _excel(c.payload, "Country Tax Rates")
        out = {}
        for i in range(1, len(df)):
            name, rate = df.iat[i, 0], pd.to_numeric(df.iat[i, 1], errors="coerce")
            if isinstance(name, str) and not pd.isna(rate):
                out[name.strip()] = float(rate)
        return out, c
