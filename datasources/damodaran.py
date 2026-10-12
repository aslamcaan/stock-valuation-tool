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
}


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
