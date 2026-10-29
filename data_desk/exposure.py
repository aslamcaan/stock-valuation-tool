"""Exposure profile (code): the channels through which outside events reach the company.

Built before the news desk searches, from the data desk and the research desk's verified extraction:
revenue by geography, commodity sensitivities (10-K disclosures, else the industry's usual inputs by SIC code),
interest-rate sensitivity (disclosure plus debt and interest expense), FX exposure, key customers, suppliers and
regulators. Macro news is only reported when it hits one of these channels, and the news desk must name it.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# SIC code ranges -> commodities that typically drive the industry's revenue or costs. Used only when the annual
# report does not disclose a sensitivity itself, and labelled as an industry default.
SIC_COMMODITIES: list[tuple[range, list[str]]] = [
    (range(1300, 1390), ["crude oil", "natural gas"]),
    (range(2910, 2912), ["crude oil", "refining margins", "natural gas"]),
    (range(4610, 4620), ["crude oil", "natural gas"]),
    (range(4920, 4926), ["natural gas"]),
    (range(4910, 4912), ["natural gas", "power prices"]),
    (range(1000, 1100), ["metals (gold, copper)"]),
    (range(1220, 1242), ["coal"]),
    (range(3310, 3318), ["iron ore", "steel prices"]),
    (range(3330, 3342), ["aluminium", "copper"]),
    (range(2800, 2870), ["natural gas", "petrochemical feedstocks"]),
    (range(4510, 4530), ["jet fuel"]),
    (range(2000, 2100), ["agricultural commodities (sugar, grains)"]),
    (range(3570, 3580), ["memory chip prices"]),
    (range(3670, 3680), ["memory chip prices"]),
]
US_STATES = {"AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "DC", "FL", "GA", "HI", "ID", "IL", "IN", "IA", "KS", "KY",
             "LA", "ME", "MD", "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ", "NM", "NY", "NC", "ND", "OH",
             "OK", "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY", "PR"}
US_NAMES = {"united states", "us", "u.s.", "usa", "u.s", "united states of america", "north america", "americas"}


@dataclass
class Exposure:
    category: str      # Geography, Commodity, Interest rates, FX, Customers, Suppliers, Regulators
    channel: str       # short name used in news analysis, e.g. "Crude oil price"
    detail: str
    source: str
    quote: str = ""


@dataclass
class ExposureProfile:
    items: list[Exposure] = field(default_factory=list)
    search_topics: list[str] = field(default_factory=list)   # macro themes to search, from the channels above
    notes: list[str] = field(default_factory=list)

    def channels(self) -> list[str]:
        return [e.channel for e in self.items]

    def for_ai(self) -> list[dict]:
        return [{"category": e.category, "channel": e.channel, "detail": e.detail, "source": e.source}
                for e in self.items]


def _sic_commodities(sic: str) -> list[str]:
    try:
        code = int(sic)
    except (TypeError, ValueError):
        return []
    return next((c for r, c in SIC_COMMODITIES if code in r), [])


def _fmt_m(x: float | None, ccy: str) -> str:
    return "n/a" if x is None else f"{ccy} {x:,.0f}m"


def _home_country(country: str | None) -> str:
    """EDGAR's business address gives a US state code for US filers, a country name otherwise."""
    c = (country or "").strip()
    return "United States" if not c or c.upper() in US_STATES or c.lower() in US_NAMES else c


def _filing_text(item: dict) -> str:
    """The filing's own words for a disclosure: the verified quote (the research desk blanks quotes it cannot find).
    The AI's paraphrase is not shown, as its numbers are not checked against the filing."""
    q = (item or {}).get("quote") or ""
    return q if len(q) <= 300 else q[:297].rsplit(" ", 1)[0] + "…"


def build_exposure(cd, research=None) -> ExposureProfile:
    """`cd` is a CompanyData; `research` is a desks.research.ResearchResult (verified data) or None."""
    r = (research.data if research else None) or {}
    p, h = cd.profile, cd.historicals
    ccy = h.currency
    filing = (research.source if research and research.source else "latest annual report")
    prof = ExposureProfile()

    # --- geography --------------------------------------------------------------------------------------------------
    geo = [g for g in r.get("geographic_mix", []) if g.get("region")]
    if geo:
        non_us = 0.0
        for g in geo:
            share = g.get("share_of_revenue_pct")
            rev = g.get("revenue_millions")
            detail = (f"{share:g}% of revenue" if share is not None else
                      f"revenue {_fmt_m(rev, ccy)}" if rev is not None else "disclosed revenue region")
            prof.items.append(Exposure("Geography", g["region"], detail, filing, g.get("quote", "")))
            if share is not None and g["region"].strip().lower() not in US_NAMES:
                non_us += share
            prof.search_topics.append(f"{g['region']} economy and consumer demand")
        if non_us:
            prof.notes.append(f"{non_us:g}% of revenue is outside the United States (sum of disclosed regions).")
    else:
        home = _home_country(p.country)
        prof.items.append(Exposure("Geography", home, "home market; the annual report's geographic split was not "
                                   "extracted", "SEC company profile"))
        prof.search_topics.append(f"{home} economy")

    # --- commodities ------------------------------------------------------------------------------------------------
    disclosed = [c for c in r.get("commodity_sensitivities", []) if c.get("commodity")]
    for c in disclosed:
        # Commodity items passed the research desk's quote and number checks, so the sensitivity text is verified.
        prof.items.append(Exposure("Commodity", c["commodity"], c.get("sensitivity_text") or "disclosed sensitivity",
                                   filing, c.get("quote", "")))
        prof.search_topics.append(f"{c['commodity']} prices")
    if not disclosed:
        for name in _sic_commodities(p.sic):
            prof.items.append(Exposure("Commodity", name, f"typical driver for SIC {p.sic} ({p.sic_description}); "
                                       "no sensitivity disclosed", "industry default (SIC code)"))
            prof.search_topics.append(f"{name} prices")

    # --- interest rates ---------------------------------------------------------------------------------------------
    last = h.ltm.label if h.ltm else (h.fy_labels[-1] if h.fy_labels else None)
    debt = h.v("debt_for_valuation", last) if last else None
    debt = debt if debt is not None else (h.v("total_debt", last) if last else None)
    cash = h.v("cash_and_investments", last) if last else None
    interest = h.v("interest_expense", last) if last else None
    irs_text = _filing_text(r.get("interest_rate_sensitivity"))
    facts = (f"debt {_fmt_m(debt, ccy)}, cash and investments {_fmt_m(cash, ccy)}, interest expense "
             f"{_fmt_m(interest, ccy)} ({last})" if last else "no balance sheet")
    prof.items.append(Exposure("Interest rates", "Interest rates",
                               (f'"{irs_text}"; ' if irs_text else "") + facts,
                               (filing + " and " if irs_text else "") + "EDGAR XBRL", irs_text))
    bank = {"EUR": "European Central Bank", "GBP": "Bank of England", "JPY": "Bank of Japan", "CAD": "Bank of Canada",
            "CHF": "Swiss National Bank", "SGD": "Monetary Authority of Singapore", "AUD": "Reserve Bank of Australia"}
    if p.reporting_currency in bank:
        prof.search_topics.append(f"{bank[p.reporting_currency]} interest rates")
    prof.search_topics.append("US Federal Reserve interest rates and Treasury yields")

    # --- FX ---------------------------------------------------------------------------------------------------------
    fx_text = _filing_text(r.get("fx_exposure"))
    if p.reporting_currency and p.reporting_currency != "USD":
        prof.items.append(Exposure("FX", f"{p.reporting_currency}/USD",
                                   f"reports in {p.reporting_currency}, shares trade in USD", "SEC company profile"))
        prof.search_topics.append(f"{p.reporting_currency} US dollar exchange rate")
    if fx_text:
        prof.items.append(Exposure("FX", "Foreign exchange", f'"{fx_text}"', filing, fx_text))
    elif geo and any(g["region"].strip().lower() not in US_NAMES for g in geo):
        prof.items.append(Exposure("FX", "Foreign exchange", "revenue earned outside the US is exposed to the US "
                                   "dollar's moves", "derived from the geographic split"))

    # --- customers, suppliers, regulators ---------------------------------------------------------------------------
    for key, cat in (("key_customers", "Customers"), ("key_suppliers", "Suppliers"), ("regulators", "Regulators")):
        for name in r.get(key, [])[:6]:
            if name:
                prof.items.append(Exposure(cat, name, cat[:-1].lower() + " named in the annual report",
                                           f"AI-extracted from {filing} (name only, no quote check)"))
    if not r:
        prof.notes.append("The research desk did not run, so the profile uses market data and industry defaults only.")
    prof.search_topics = list(dict.fromkeys(prof.search_topics))[:6]
    return prof
