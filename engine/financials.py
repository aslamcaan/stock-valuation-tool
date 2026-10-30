"""Financial-sector toolkits (pure): banks, insurers and REITs. PROMPT.md section 8.

A DCF does not work for these businesses: debt is raw material rather than financing (banks, insurers), and for
REITs value sits in the property book. So:

- Banks: justified P/TBV = (ROTE - g) / (CoE - g), a residual income model on tangible book, a two-stage dividend
  discount model, and peer P/E and P/TBV.
- Insurers: the same on book value and ROE (justified P/B), with peer P/E and P/B.
- REITs: NAV (NOI / cap rate - net debt, cap rate implied by peers and editable), peer P/FFO, and a DDM.

Cost of equity is CAPM with a levered beta. Long-run growth g is the lowest of sustainable growth (normalised return
x retention), the risk-free rate less 0.5 points and 3%. Each method's figures are Values, so every number traces.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from statistics import mean, median

from engine.classify import BANK, INSURER, REIT
from engine.flags import AMBER, HARD_STOP, INFO, RED, Flag
from engine.model import Historicals
from engine.values import MILLIONS, MULTIPLE, PER_SHARE, RATIO, Value, calc

WEIGHTS = {
    BANK: {"justified": 0.30, "residual_income": 0.30, "ddm": 0.10, "comps_pb": 0.15, "comps_pe": 0.15},
    INSURER: {"justified": 0.30, "residual_income": 0.30, "ddm": 0.10, "comps_pb": 0.15, "comps_pe": 0.15},
    REIT: {"nav": 0.40, "comps_pffo": 0.30, "ddm": 0.30},
}
METHOD_LABELS = {
    "justified": {BANK: "Justified P/TBV (ROTE vs cost of equity)", INSURER: "Justified P/B (ROE vs cost of equity)"},
    "residual_income": {BANK: "Residual income (excess return on tangible book)",
                        INSURER: "Residual income (excess return on book)"},
    "ddm": "Dividend discount model (two-stage)",
    "comps_pb": {BANK: "Peer P/TBV", INSURER: "Peer P/B"},
    "comps_pe": "Peer P/E (trailing)",
    "nav": "Net asset value (NOI / cap rate - net debt)",
    "comps_pffo": "Peer P/FFO",
}
WHY_NO_DCF = {
    BANK: "Banks are valued on equity, not enterprise value: deposits and debt are the raw material of lending, so "
          "free cash flow and WACC are not meaningful. The tool uses returns on tangible book against the cost of "
          "equity, residual income, dividends and peer multiples instead.",
    INSURER: "Insurers are valued on equity: float and reserves fund the investment portfolio, so free cash flow and "
             "WACC are not meaningful. The tool uses returns on book against the cost of equity, residual income, "
             "dividends and peer multiples instead.",
    REIT: "A REIT's value sits in its properties and it must pay out most of its income, so a standard DCF on "
          "accounting cash flow is not used. The tool uses net asset value (NOI capitalised at a cap rate), funds "
          "from operations multiples and dividends instead.",
}
RI_YEARS = 10
DDM_YEARS = 5
FADE_TO_NORMAL = 3          # years for the return to move from the latest to the normalised level
EXCESS_KEPT = 0.5           # share of the normalised excess return still earned in year 10 (competition erodes it)
MAX_STAGE1_GROWTH = 0.10
MIN_PEERS = 3


def method_label(key: str, toolkit: str) -> str:
    x = METHOD_LABELS[key]
    return x[toolkit] if isinstance(x, dict) else x


@dataclass
class FinInputs:
    toolkit: str
    historicals: Historicals            # US$ millions
    price: Value                        # per US share
    shares: Value                       # millions of ordinary shares
    adr_ratio: float
    risk_free: Value
    erp: Value
    crp: Value
    beta: Value                         # levered
    reported: dict = field(default_factory=dict)   # key -> Value read from the annual report text
    peers: list = field(default_factory=list)      # CompanyMetrics (comps.py)
    overrides: dict = field(default_factory=dict)


@dataclass
class Metric:
    key: str
    label: str
    group: str
    value: Value                 # computed by the tool (may be missing)
    reported: Value | None = None  # as the company reports it (annual report text)


@dataclass
class FinancialValuation:
    toolkit: str
    why_no_dcf: str
    period: str
    metrics: list[Metric]
    cost_of_equity: Value
    growth: Value
    normalised_return: Value | None
    base_per_share: Value | None          # TBVPS (bank), BVPS (insurer); None for REITs
    methods: dict[str, Value]             # per US share
    detail: dict[str, dict]               # tables behind each method (years, peers)
    weights: dict[str, float]
    assumptions: list[dict]
    flags: list[Flag]
    per_us_share_factor: float

    def metric(self, key: str) -> Metric | None:
        return next((m for m in self.metrics if m.key == key), None)

    def per_us_share(self, x: float | None) -> float | None:
        return None if x is None else x * self.per_us_share_factor


class FinancialError(Exception):
    pass


# --- helpers -------------------------------------------------------------------------------------------------------
def _v(h: Historicals, line: str, p: str | None) -> Value:
    v = h.get(line, p) if p else None
    return v if v is not None else Value(None, "USD", MILLIONS, p or "", "not reported", note=f"{line} not reported")


def _zero_if_missing(h: Historicals, line: str, p: str) -> Value:
    v = h.get(line, p)
    if v is not None and v.value is not None:
        return v
    return Value(0.0, "USD", MILLIONS, p, "assumed zero", note=f"{line} not reported: taken as zero")


def _avg(a: Value, b: Value | None, label: str) -> Value:
    if b is None or b.value is None:
        return a
    return calc(lambda x, y: (x + y) / 2, f"average {label} (start and end of year)", a.period, a.unit, a.currency,
                end=a, start=b)


def _ratio(n: Value, d: Value, formula: str, period: str) -> Value:
    return calc(lambda a, b: a / b, formula, period, RATIO, None, numerator=n, denominator=d)


def common_equity(h: Historicals, p: str) -> Value:
    return calc(lambda e, pref: e - pref, "shareholders' equity - preferred stock", p, MILLIONS, "USD",
                equity=_v(h, "parent_equity", p), preferred=_zero_if_missing(h, "preferred_equity", p))


def tangible_common_equity(h: Historicals, p: str) -> Value:
    return calc(lambda c, g, i: c - g - i, "common equity - goodwill - other intangibles", p, MILLIONS, "USD",
                common_equity=common_equity(h, p), goodwill=_zero_if_missing(h, "goodwill", p),
                intangibles=_zero_if_missing(h, "intangibles", p))


def ni_common(h: Historicals, p: str) -> Value:
    v = h.get("net_income_common", p)
    if v is not None and v.value is not None:
        return v
    return calc(lambda n, d: n - d, "net income to shareholders - preferred dividends", p, MILLIONS, "USD",
                net_income=_v(h, "net_income_attributable", p),
                preferred_dividends=_zero_if_missing(h, "preferred_dividends", p))


def ffo(h: Historicals, p: str) -> Value:
    """Nareit FFO: net income to common + depreciation and amortisation + impairments - gains on property sales.
    Uses total D&A (the real-estate share is not tagged separately), so it can run slightly above reported FFO."""
    return calc(lambda n, d, i, g: n + d + i - g,
                "net income to common + D&A + real estate impairments - gains on sale of real estate", p,
                MILLIONS, "USD", net_income_common=ni_common(h, p), d_and_a=_v(h, "d_and_a", p),
                impairments=_zero_if_missing(h, "real_estate_impairment", p),
                gains=_zero_if_missing(h, "real_estate_gains", p))


def noi_proxy(h: Historicals, p: str) -> Value:
    """NOI is not a GAAP line: proxied by Nareit EBITDAre (net income + interest + tax + D&A + impairments - gains
    on property sales). It is after G&A, so a conservative NOI; peers' cap rates use the same measure."""
    ni = h.get("net_income", p) or _v(h, "net_income_attributable", p)
    return calc(lambda n, i, t, d, imp, g: n + i + t + d + imp - g,
                "EBITDAre: net income + interest expense + income tax + D&A + real estate impairments - gains on sale",
                p, MILLIONS, "USD", net_income=ni, interest_expense=_v(h, "interest_expense", p),
                income_tax=_zero_if_missing(h, "income_tax", p), d_and_a=_v(h, "d_and_a", p),
                impairments=_zero_if_missing(h, "real_estate_impairment", p),
                gains=_zero_if_missing(h, "real_estate_gains", p))


def total_payout(h: Historicals, years: int = 3) -> Value:
    """(Dividends + buybacks) / net income, averaged over the last `years` fiscal years, bounded 0-100%. Book per
    share grows only by what is neither paid out nor bought back, so this (not the dividend payout) sets retention."""
    rows = []
    for p in h.fy_labels[-years:]:
        ni = h.v("net_income_attributable", p)
        div, bb = h.v("dividends_paid", p), h.v("buybacks", p)
        if ni and ni > 0 and (div is not None or bb is not None):
            rows.append(min(max((abs(div or 0.0) + abs(bb or 0.0)) / ni, 0.0), 1.0))
    if not rows:
        return Value(None, None, RATIO, "", "not available", note="dividends and buybacks not reported")
    return Value(mean(rows), None, RATIO, f"{h.fy_labels[-len(rows)]}-{h.fy_labels[-1]}", "calculated",
                 formula=f"(dividends paid + share repurchases) / net income, average of {len(rows)} years "
                         "(bounded 0-100%)")


def dividend_per_share(h: Historicals, p: str) -> Value | None:
    v = h.get("dps_declared", p)
    if v is not None and v.value:
        return v
    d = calc(lambda a, s: abs(a) / s, "dividends paid / weighted basic shares", p, PER_SHARE, "USD",
             dividends_paid=_v(h, "dividends_paid", p), shares=_v(h, "shares_basic_weighted", p))
    return d if d.value else None


def returns_on_book(h: Historicals, toolkit: str) -> dict[str, Value]:
    """Return on (tangible, for banks) common equity for each fiscal year with an opening balance."""
    out = {}
    fy = h.fy_labels
    book = tangible_common_equity if toolkit == BANK else common_equity
    for prev, p in zip(fy, fy[1:]):
        r = calc(lambda n, b: n / b, f"net income to common / average {'tangible ' if toolkit == BANK else ''}"
                 f"common equity ({p})", p, RATIO, None, net_income_common=ni_common(h, p),
                 average_equity=_avg(book(h, p), book(h, prev), "equity"))
        if r.value is not None:
            out[p] = r
    return out


# --- metrics -------------------------------------------------------------------------------------------------------
def bank_metrics(h: Historicals, p: str, prev: str | None, shares: Value, rep: dict) -> list[Metric]:
    nii, nonint = _v(h, "net_interest_income", p), _v(h, "noninterest_income", p)
    revenue = calc(lambda a, b: a + b, "net interest income + noninterest income", p, MILLIONS, "USD",
                   net_interest_income=nii, noninterest_income=nonint)
    avg_assets = _avg(_v(h, "total_assets", p), h.get("total_assets", prev) if prev else None, "total assets")
    loans = _v(h, "loans_gross", p)
    avg_loans = _avg(loans, h.get("loans_gross", prev) if prev else None, "loans")
    tce, ce = tangible_common_equity(h, p), common_equity(h, p)
    tce0 = tangible_common_equity(h, prev) if prev else None
    ce0 = common_equity(h, prev) if prev else None
    nic = ni_common(h, p)
    tbvps = calc(lambda t, s: t / s, "tangible common equity / shares outstanding", p, PER_SHARE, "USD",
                 tangible_common_equity=tce, shares=shares)
    bvps = calc(lambda c, s: c / s, "common equity / shares outstanding", p, PER_SHARE, "USD",
                common_equity=ce, shares=shares)
    m = [
        Metric("nim", "Net interest margin", "Profitability",
               _ratio(nii, avg_assets, "net interest income / average total assets (proxy: the reported margin uses "
                                       "average interest-earning assets)", p), rep.get("nim")),
        Metric("efficiency_ratio", "Efficiency ratio", "Profitability",
               _ratio(_v(h, "noninterest_expense", p), revenue, "noninterest expense / revenue", p),
               rep.get("efficiency_ratio")),
        Metric("rote", "Return on tangible common equity", "Profitability",
               _ratio(nic, _avg(tce, tce0, "tangible common equity"), "net income to common / average tangible "
                      "common equity", p), rep.get("rotce")),
        Metric("roe", "Return on common equity", "Profitability",
               _ratio(nic, _avg(ce, ce0, "common equity"), "net income to common / average common equity", p),
               rep.get("roe")),
        Metric("roa", "Return on assets", "Profitability",
               _ratio(_v(h, "net_income_attributable", p), avg_assets, "net income / average total assets", p)),
        Metric("fee_mix", "Fee income share of revenue", "Profitability",
               _ratio(nonint, revenue, "noninterest income / revenue", p)),
        Metric("cet1_ratio", "CET1 ratio", "Capital", _missing("CET1 is not in XBRL; see the reported figure", p),
               rep.get("cet1_ratio")),
        Metric("tier1_leverage_ratio", "Tier 1 leverage ratio", "Capital",
               _missing("not in XBRL; see the reported figure", p), rep.get("tier1_leverage_ratio")),
        Metric("slr", "Supplementary leverage ratio", "Capital", _missing("not in XBRL; see the reported figure", p),
               rep.get("slr")),
        Metric("loan_to_deposit", "Loans / deposits", "Balance sheet",
               _ratio(loans, _v(h, "deposits", p), "loans (before allowance) / deposits", p)),
        Metric("npl_ratio", "Nonaccrual loans / loans", "Asset quality",
               _ratio(_v(h, "nonaccrual_loans", p), loans, "nonaccrual loans / loans", p)),
        Metric("nco_rate", "Net charge-offs / average loans", "Asset quality",
               _ratio(_v(h, "net_charge_offs", p), avg_loans, "net charge-offs / average loans", p)),
        Metric("provision_rate", "Provisions / average loans", "Asset quality",
               _ratio(_v(h, "provision_credit_losses", p), avg_loans, "provision for credit losses / average loans",
                      p)),
        Metric("allowance_ratio", "Allowance / loans", "Asset quality",
               _ratio(_v(h, "loan_allowance", p), loans, "allowance for loan losses / loans", p)),
        Metric("bvps", "Book value per share", "Per share", bvps, rep.get("bvps")),
        Metric("tbvps", "Tangible book value per share", "Per share", tbvps, rep.get("tbvps")),
    ]
    if prev:
        m.append(Metric("tbvps_growth", "Tangible book value per share growth", "Per share",
                        _growth(tbvps, calc(lambda t, s: t / s, "tangible common equity / shares", prev, PER_SHARE,
                                            "USD", tangible_common_equity=tce0,
                                            shares=_v(h, "shares_outstanding", prev)), p)))
    m.append(Metric("nii_sensitivity", "Net interest income sensitivity to rates", "Rates",
                    _missing("disclosed as a table of scenarios in Item 7A; not extracted automatically", p)))
    return m


def insurer_metrics(h: Historicals, p: str, prev: str | None, shares: Value, rep: dict) -> list[Metric]:
    pe = _v(h, "premiums_earned", p)
    loss_ratio = _ratio(_v(h, "losses_incurred", p), pe, "claims and claim adjustment expenses / net premiums earned",
                        p)
    ce, ce0 = common_equity(h, p), common_equity(h, prev) if prev else None
    bvps = calc(lambda c, s: c / s, "common equity / shares outstanding", p, PER_SHARE, "USD",
                common_equity=ce, shares=shares)
    m = [
        Metric("combined_ratio", "Combined ratio", "Underwriting",
               _missing("needs underwriting expenses, which are not tagged consistently; see the reported figure", p),
               rep.get("combined_ratio")),
        Metric("loss_ratio", "Loss and LAE ratio", "Underwriting", loss_ratio, rep.get("loss_ratio")),
        Metric("expense_ratio", "Underwriting expense ratio", "Underwriting",
               _missing("see the reported figure", p), rep.get("expense_ratio")),
        Metric("reserve_development", "Prior-year reserve development / premiums earned", "Underwriting",
               _ratio(_v(h, "prior_year_development", p), pe, "prior-year development / net premiums earned "
                                                              "(negative = favourable)", p)),
        Metric("investment_yield", "Net investment income / average total assets", "Investments",
               _ratio(_v(h, "net_investment_income", p),
                      _avg(_v(h, "total_assets", p), h.get("total_assets", prev) if prev else None, "total assets"),
                      "net investment income / average total assets (invested assets are not tagged)", p)),
        Metric("roe", "Return on common equity", "Profitability",
               _ratio(ni_common(h, p), _avg(ce, ce0, "common equity"), "net income to common / average common "
                                                                       "equity", p)),
        Metric("bvps", "Book value per share", "Per share", bvps, rep.get("bvps")),
        Metric("solvency", "Solvency / capital ratio", "Capital",
               _missing("statutory capital (RBC) is filed with state regulators, not in the 10-K XBRL", p)),
    ]
    if prev:
        m.append(Metric("premium_growth", "Net premiums earned growth", "Underwriting",
                        _growth(pe, _v(h, "premiums_earned", prev), p)))
        m.append(Metric("bvps_growth", "Book value per share growth", "Per share",
                        _growth(bvps, calc(lambda c, s: c / s, "common equity / shares", prev, PER_SHARE, "USD",
                                           common_equity=ce0, shares=_v(h, "shares_outstanding", prev)), p)))
    return m


def reit_metrics(h: Historicals, p: str, prev: str | None, rep: dict) -> list[Metric]:
    f = ffo(h, p)
    sh = h.get("shares_diluted_weighted", p) or _v(h, "shares_basic_weighted", p)
    ffo_ps = calc(lambda a, s: a / s, "FFO / weighted diluted shares", p, PER_SHARE, "USD", ffo=f, shares=sh)
    noi = noi_proxy(h, p)
    debt = _v(h, "total_debt", p)
    ebitda = h.get("ebitda", p) if h.v("ebitda", p) else noi_proxy(h, p)
    dps = dividend_per_share(h, p) or _v(h, "dps_declared", p)
    affo = rep.get("affo_per_share")
    return [
        Metric("ffo", "Funds from operations (FFO)", "Earnings", f),
        Metric("ffo_per_share", "FFO per share", "Earnings", ffo_ps, rep.get("ffo_per_share")),
        Metric("affo_per_share", "AFFO per share", "Earnings",
               _missing("AFFO is company-defined (straight-line rent, maintenance capex); see the reported figure", p),
               affo),
        Metric("noi", "Net operating income (proxy)", "Earnings", noi),
        Metric("occupancy", "Occupancy", "Portfolio", _missing("see the reported figure", p), rep.get("occupancy")),
        Metric("same_store_noi_growth", "Same-store NOI growth", "Portfolio",
               _missing("disclosed in the supplement, not extracted automatically", p)),
        Metric("lease_expiry", "Lease expiry profile", "Portfolio",
               _missing("disclosed as a table, not extracted automatically", p)),
        Metric("debt_to_ebitda", "Debt / EBITDA", "Balance sheet",
               calc(lambda d, e: d / e if e > 0 else None, "total debt / EBITDA", p, MULTIPLE, None, debt=debt,
                    ebitda=ebitda)),
        Metric("affo_payout", "Dividend / AFFO per share", "Payout",
               calc(lambda d, a: d / a, "dividends declared per share / reported AFFO per share", p, RATIO, None,
                    dps=dps, affo=affo) if affo is not None else _missing("needs reported AFFO", p)),
        Metric("ffo_payout", "Dividend / FFO per share", "Payout",
               calc(lambda d, a: d / a, "dividends declared per share / FFO per share", p, RATIO, None, dps=dps,
                    ffo_per_share=ffo_ps)),
    ]


def _missing(note: str, p: str) -> Value:
    return Value(None, None, RATIO, p, "not available", note=note)


def _growth(now: Value, before: Value, p: str) -> Value:
    return calc(lambda a, b: a / b - 1 if b > 0 else None, "year-on-year growth", p, RATIO, None, now=now,
                before=before)


# --- valuation methods ---------------------------------------------------------------------------------------------
def cost_of_equity(i: FinInputs) -> Value:
    if i.overrides.get("cost_of_equity") is not None:
        return Value(float(i.overrides["cost_of_equity"]), None, RATIO, "current", "user override")
    return calc(lambda rf, b, erp, crp: rf + b * erp + crp, "risk-free + levered beta x equity risk premium + "
                "country risk premium", "current", RATIO, None, risk_free=i.risk_free, beta=i.beta, erp=i.erp,
                crp=i.crp)


def justified_multiple(ret: float, coe: float, g: float) -> float:
    if coe - g <= 0:
        raise FinancialError("cost of equity at or below long-run growth")
    return (ret - g) / (coe - g)


def residual_income(base: float, latest: float, normal: float, coe: float, g: float, retention: float,
                    years: int = RI_YEARS, fade: int = FADE_TO_NORMAL, kept: float = EXCESS_KEPT) -> dict:
    """Value per share = book today + PV of (return - CoE) x opening book, then a terminal value growing at g.
    The return moves from the latest year to the normalised level over `fade` years, then the excess over the cost
    of equity shrinks so that only `kept` of it is earned by year `years`. Book grows by retained earnings."""
    if coe - g <= 0:
        raise FinancialError("cost of equity at or below long-run growth")
    rows, b, pv = [], base, 0.0
    long_run = coe + kept * (normal - coe)
    for t in range(1, years + 1):
        if t <= fade:
            r = latest + (normal - latest) * t / fade
        else:
            r = normal + (long_run - normal) * (t - fade) / (years - fade)
        ri = (r - coe) * b
        df = (1 + coe) ** -t
        pv += ri * df
        rows.append({"year": t, "opening_book": b, "return": r, "residual_income": ri, "discount_factor": df,
                     "pv": ri * df})
        b = b * (1 + r * retention)
    terminal = (long_run - coe) * b / (coe - g)  # year-11 residual income on year-10 closing book, growing at g
    pv_terminal = terminal * (1 + coe) ** -years
    return {"rows": rows, "terminal_value": terminal, "pv_terminal": pv_terminal, "pv_explicit": pv,
            "value": base + pv + pv_terminal, "long_run_return": long_run}


def ddm(dps0: float, g1: float, g: float, coe: float, years: int = DDM_YEARS) -> dict:
    if coe - g <= 0:
        raise FinancialError("cost of equity at or below long-run growth")
    rows, pv, d = [], 0.0, dps0
    for t in range(1, years + 1):
        d = d * (1 + g1)
        df = (1 + coe) ** -t
        pv += d * df
        rows.append({"year": t, "dividend": d, "discount_factor": df, "pv": d * df})
    terminal = d * (1 + g) / (coe - g)
    pv_terminal = terminal * (1 + coe) ** -years
    return {"rows": rows, "terminal_value": terminal, "pv_terminal": pv_terminal, "pv_explicit": pv,
            "value": pv + pv_terminal, "stage1_growth": g1}


def peer_multiple(peers: list, fn) -> tuple[float | None, list[dict]]:
    used = []
    for c in peers:
        try:
            x = fn(c)
        except (TypeError, ZeroDivisionError):
            x = None
        if x is not None and x > 0:
            used.append({"ticker": c.ticker, "name": c.name, "multiple": x, "period": c.period})
    if len(used) < MIN_PEERS:
        return None, used
    return median(u["multiple"] for u in used), used


def _pos(n, d):
    return n / d if n is not None and d is not None and d > 0 and n > 0 else None


def value_financial(i: FinInputs) -> FinancialValuation:
    h, tk = i.historicals, i.toolkit
    if tk not in WEIGHTS:
        raise FinancialError(f"no financial toolkit for '{tk}'")
    fy = h.fy_labels
    if not fy:
        raise FinancialError("no annual statements")
    p = fy[-1]
    prev = fy[-2] if len(fy) > 1 else None
    rep = i.reported
    flags: list[Flag] = []
    shares = i.shares
    if tk == BANK:
        metrics = bank_metrics(h, p, prev, shares, rep)
    elif tk == INSURER:
        metrics = insurer_metrics(h, p, prev, shares, rep)
    else:
        metrics = reit_metrics(h, p, prev, rep)

    coe = cost_of_equity(i)
    rf = i.risk_free.value
    nic = ni_common(h, p)
    eps = calc(lambda n, s: n / s, "net income to common / shares outstanding", p, PER_SHARE, "USD",
               net_income_common=nic, shares=shares)
    dps = dividend_per_share(h, p)
    tp = total_payout(h)
    payout = calc(lambda d, e: min(max(d / e, 0.0), 1.0) if e > 0 else None, "dividends per share / earnings per "
                  "share (bounded 0-100%)", p, RATIO, None, dps=dps, eps=eps) if dps is not None else \
        Value(None, None, RATIO, p, "not available", note="dividends per share not reported")
    methods: dict[str, Value] = {}
    detail: dict[str, dict] = {}
    assumptions: list[dict] = []
    normal = base = None
    cap = min(rf - 0.005, 0.03)

    if tk in (BANK, INSURER):
        rets = returns_on_book(h, tk)
        hist = [rets[k] for k in sorted(rets)][-5:]
        latest = hist[-1] if hist else None
        if latest is None:
            raise FinancialError("return on equity cannot be computed (net income or equity missing)")
        normal = Value(mean(x.value for x in hist), None, RATIO, f"{hist[0].period}-{hist[-1].period}", "calculated",
                       formula=f"average of {len(hist)} years' return on {'tangible ' if tk == BANK else ''}common "
                               f"equity (normalised through the cycle)", inputs=tuple(hist))
        if i.overrides.get("normalised_return") is not None:
            normal = Value(float(i.overrides["normalised_return"]), None, RATIO, "current", "user override")
        base_line = "tbvps" if tk == BANK else "bvps"
        mt = next(m for m in metrics if m.key == base_line)
        base = mt.reported if mt.reported is not None else mt.value
        if base.value is None or base.value <= 0:
            raise FinancialError(f"Cannot value: {mt.label.lower()} is unavailable or not positive (book-based "
                                 "methods need positive book value).")
        if mt.reported is not None and mt.value.value and abs(mt.reported.value / mt.value.value - 1) > 0.05:
            flags.append(Flag(AMBER, "book_vs_reported", f"{mt.label}: computed differs from reported",
                              f"Computed {mt.value.value:.2f} vs reported {mt.reported.value:.2f} per share; the "
                              "valuation uses the reported figure (the company's own definition).", p, {}))
        # book grows by what is neither paid as dividends nor spent on buybacks
        used_payout = tp if tp.value is not None else payout
        retention = 1 - (used_payout.value if used_payout.value is not None else 0.0)
        sust = normal.value * retention
        g_val = i.overrides.get("long_run_growth")
        g = Value(float(g_val), None, RATIO, "current", "user override") if g_val is not None else Value(
            max(0.0, min(sust, cap)), None, RATIO, "current", "calculated",
            formula="lowest of sustainable growth (normalised return x retention), risk-free - 0.5 points and 3%; "
                    "not below zero", inputs=(normal, used_payout, i.risk_free))
        if coe.value - g.value <= 0.005:
            flags.append(Flag(HARD_STOP, "coe_below_growth", "Cost of equity at or below long-run growth",
                              f"Cost of equity {coe.value:.1%} vs growth {g.value:.1%}: no finite value.", None, {}))
            raise FinancialError(f"Hard stop: cost of equity {coe.value:.1%} is not above long-run growth "
                                 f"{g.value:.1%}.")
        jm = justified_multiple(normal.value, coe.value, g.value)
        methods["justified"] = Value(jm * base.value, "USD", PER_SHARE, "current", "calculated",
                                     formula=f"(normalised return - g) / (cost of equity - g) x "
                                             f"{'tangible ' if tk == BANK else ''}book value per share",
                                     inputs=(normal, g, coe, base))
        detail["justified"] = {"multiple": jm, "return": normal.value, "coe": coe.value, "g": g.value,
                               "base": base.value}
        ri = residual_income(base.value, latest.value, normal.value, coe.value, g.value, retention)
        methods["residual_income"] = Value(ri["value"], "USD", PER_SHARE, "current", "calculated",
                                           formula="book value per share + PV of residual income + PV of terminal "
                                                   "value", inputs=(base, latest, normal, coe, g))
        detail["residual_income"] = ri | {"retention": retention, "latest_return": latest.value}
        assumptions += [
            {"name": "Normalised return", "value": normal.value, "unit": RATIO, "basis": normal.formula or "",
             "editable": "normalised_return"},
            {"name": "Long-run growth", "value": g.value, "unit": RATIO, "basis": g.formula or g.source,
             "editable": "long_run_growth"},
            {"name": "Excess return kept by year 10", "value": EXCESS_KEPT, "unit": RATIO,
             "basis": "competition erodes returns above the cost of equity over time", "editable": None},
        ]
        bm = next(m for m in metrics if m.key == ("rote" if tk == BANK else "roe"))
        rep_ret = bm.reported.value if bm.reported is not None else None
        if rep_ret is not None and bm.value.value is not None and abs(rep_ret - bm.value.value) > 0.02:
            flags.append(Flag(INFO, "return_vs_reported", f"{bm.label}: computed differs from reported",
                              f"Computed {bm.value.value:.1%} vs reported {rep_ret:.1%} (definitions differ, e.g. "
                              "deferred tax on intangibles or average balances).", p, {}))
        if latest.value > normal.value + 0.05:
            flags.append(Flag(AMBER, "return_above_normal", "Latest return well above its 5-year average",
                              f"{latest.value:.1%} in {p} vs {normal.value:.1%} average: possibly a cyclical peak.",
                              p, {}))
        if normal.value < coe.value:
            flags.append(Flag(AMBER, "return_below_coe", "Returns below the cost of equity",
                              f"Normalised return {normal.value:.1%} vs cost of equity {coe.value:.1%}: the "
                              "business is destroying value at the margin, so it is worth less than book.", p, {}))
        # comps on book and earnings
        if tk == BANK:
            m_pb, used_pb = peer_multiple(i.peers, lambda c: _pos(c.market_cap, c.tangible_equity))
        else:
            m_pb, used_pb = peer_multiple(i.peers, lambda c: _pos(c.market_cap, c.common_equity))
        if m_pb is not None:
            methods["comps_pb"] = Value(m_pb * base.value, "USD", PER_SHARE, "current", "calculated",
                                        formula=f"peer median {'P/TBV' if tk == BANK else 'P/B'} x book value per "
                                                "share", inputs=(base,))
        detail["comps_pb"] = {"median": m_pb, "peers": used_pb}
    else:  # REIT
        g_val = i.overrides.get("long_run_growth")
        g = Value(float(g_val), None, RATIO, "current", "user override") if g_val is not None else Value(
            max(0.0, min(0.02, cap)), None, RATIO, "current", "calculated",
            formula="lowest of 2% (rent escalators), risk-free - 0.5 points; not below zero", inputs=(i.risk_free,))
        if coe.value - g.value <= 0.005:
            raise FinancialError(f"Hard stop: cost of equity {coe.value:.1%} is not above long-run growth "
                                 f"{g.value:.1%}.")
        noi = next(m for m in metrics if m.key == "noi").value
        m_cap, used_cap = peer_multiple(i.peers, lambda c: _pos(c.noi, c.ev))
        cap_rate = None
        if i.overrides.get("cap_rate") is not None:
            cap_rate = Value(float(i.overrides["cap_rate"]), None, RATIO, "current", "user override")
        elif m_cap is not None:
            cap_rate = Value(m_cap, None, RATIO, "current", "calculated",
                             formula=f"median of {len(used_cap)} peers' NOI proxy / enterprise value")
        detail["cap_rate"] = {"median": m_cap, "peers": used_cap}
        if cap_rate is not None and noi.value:
            net_debt = calc(lambda d, c, mi, pr: d - c + mi + pr, "debt - cash + minority interests + preferred",
                            p, MILLIONS, "USD", debt=_zero_if_missing(h, "total_debt", p),
                            cash=_zero_if_missing(h, "cash_and_investments", p),
                            minority=_zero_if_missing(h, "minority_interest", p),
                            preferred=_zero_if_missing(h, "preferred_equity", p))
            nav = calc(lambda n, c, nd, s: (n / c - nd) / s, "(NOI / cap rate - net debt) / shares outstanding",
                       "current", PER_SHARE, "USD", noi=noi, cap_rate=cap_rate, net_debt=net_debt, shares=shares)
            if nav.value is not None and nav.value > 0:
                methods["nav"] = nav
            detail["nav"] = {"noi": noi.value, "cap_rate": cap_rate.value, "net_debt": net_debt.value,
                             "gross_asset_value": noi.value / cap_rate.value, "shares": shares.value,
                             "cap_rate_overridden": cap_rate.source == "user override", "value": nav.value}
            assumptions.append({"name": "Cap rate", "value": cap_rate.value, "unit": RATIO,
                                "basis": cap_rate.formula or cap_rate.source, "editable": "cap_rate"})
        f_ps = next(m for m in metrics if m.key == "ffo_per_share")
        ffo_base = f_ps.reported if f_ps.reported is not None else f_ps.value
        m_pffo, used_pffo = peer_multiple(i.peers, lambda c: _pos(c.market_cap, c.ffo))
        if m_pffo is not None and ffo_base.value:
            methods["comps_pffo"] = Value(m_pffo * ffo_base.value, "USD", PER_SHARE, "current", "calculated",
                                          formula="peer median P/FFO x FFO per share", inputs=(ffo_base,))
        detail["comps_pffo"] = {"median": m_pffo, "peers": used_pffo}
        if f_ps.reported is not None and f_ps.value.value and abs(f_ps.reported.value / f_ps.value.value - 1) > 0.05:
            flags.append(Flag(AMBER, "ffo_vs_reported", "FFO per share: computed differs from reported",
                              f"Computed {f_ps.value.value:.2f} vs reported {f_ps.reported.value:.2f}; the "
                              "valuation uses the reported figure.", p, {}))
        assumptions.append({"name": "Long-run dividend growth", "value": g.value, "unit": RATIO,
                            "basis": g.formula or g.source, "editable": "long_run_growth"})

    # comps on earnings (banks, insurers)
    if tk in (BANK, INSURER):
        m_pe, used_pe = peer_multiple([c for c in i.peers if c.pe_meaningful],
                                      lambda c: _pos(c.market_cap, c.net_income_common or c.net_income))
        if m_pe is not None and eps.value and eps.value > 0:
            methods["comps_pe"] = Value(m_pe * eps.value, "USD", PER_SHARE, "current", "calculated",
                                        formula="peer median trailing P/E x earnings per share", inputs=(eps,))
        detail["comps_pe"] = {"median": m_pe, "peers": used_pe, "eps": eps.value}

    # dividend discount model
    if dps is not None and dps.value and dps.value > 0:
        if tk == REIT:
            g1 = g.value
            g1_note = "long-run growth (REIT dividends track rents)"
        else:
            g1 = max(0.0, min(normal.value * retention, MAX_STAGE1_GROWTH))
            g1_note = f"sustainable growth = normalised return x retention, capped at {MAX_STAGE1_GROWTH:.0%}"
        d = ddm(dps.value, g1, g.value, coe.value)
        methods["ddm"] = Value(d["value"], "USD", PER_SHARE, "current", "calculated",
                               formula=f"PV of {DDM_YEARS} years' dividends growing at stage-1 rate + Gordon terminal "
                                       "value at long-run growth", inputs=(dps, coe, g))
        detail["ddm"] = d | {"dps0": dps.value, "stage1_note": g1_note}
        if tk != REIT:
            flags.append(Flag(INFO, "ddm_buybacks", "Dividend model ignores buybacks",
                              "The DDM values dividends only, so it understates value for companies that return "
                              "much of their capital through buybacks; it carries a low weight.", None, {}))

    # per US share
    factor = i.adr_ratio or 1.0
    methods = {k: Value(v.value * factor if v.value is not None else None, v.currency, v.unit, v.period, v.source,
                        formula=v.formula + (f" x {factor:g} ordinary shares per US share" if factor != 1 else ""),
                        inputs=v.inputs) for k, v in methods.items() if v.value is not None and v.value > 0}
    weights = dict(WEIGHTS[tk])
    if i.overrides.get("blend_weights"):
        weights = {k: float(v) for k, v in i.overrides["blend_weights"].items() if k in weights}
    if not (0.06 <= coe.value <= 0.15):
        flags.append(Flag(AMBER, "coe_range", "Cost of equity outside 6-15%",
                          f"Cost of equity {coe.value:.1%}.", None, {}))
    if g.value >= rf or g.value > 0.04:
        flags.append(Flag(AMBER, "tg_vs_rf", "Long-run growth at or above the risk-free rate or 4%",
                          f"Growth {g.value:.1%} vs risk-free {rf:.1%}.", None, {}))
    for key, m in [(m.key, m) for m in metrics]:
        if m.reported is None and m.value.value is None and key in ("cet1_ratio", "combined_ratio", "affo_per_share"):
            flags.append(Flag(AMBER, f"{key}_missing", f"{m.label} not found in the annual report",
                              f"The tool could not read the company's reported {m.label.lower()} from the 10-K "
                              "text, so it is missing from the report.", p, {}))
    return FinancialValuation(tk, WHY_NO_DCF[tk], p, metrics, coe, g, normal, base, methods, detail, weights,
                              assumptions, flags, factor)
