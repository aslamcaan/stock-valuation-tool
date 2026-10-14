"""Corporate valuation orchestrator (pure): classification -> WACC -> forecast -> DCF -> scenarios,
sensitivities, reverse DCF, SOTP, plus the valuation flags. Takes EngineInputs, returns Valuation.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from statistics import median

from engine.analysis import Analysis
from engine.classify import CYCLICAL, DECLINING, Classification, classify, cycle_position
from engine.dcf import DCFError, DCFInputs, DCFResult, run_dcf
from engine.flags import AMBER, HARD_STOP, Flag
from engine.forecast import ConsensusYear, ForecastPlan, build_plan, to_dcf_inputs
from engine.model import Historicals
from engine.scenarios import (DEFAULT_SCENARIOS, ScenarioResult, grid_growth_margin, grid_wacc_growth, reverse_dcf,
                              run_scenarios)
from engine.shares import diluted_shares
from engine.sotp import Segment, SOTPResult, run_sotp
from engine.values import MILLIONS, PER_SHARE, RATIO, SHARES_M, Value, calc
from engine.wacc import WaccInputs, WaccResult, compute_wacc, synthetic_rating

LARGE_FIRM_MCAP = 5_000.0  # US$m: Damodaran's large-firm rating table above this
NET_CASH_RATING_FLOOR = "A3/A-"  # a company with more cash than debt is not rated below this
RELATIVE_EQUITY_VOL = 1.52  # Damodaran ctryprem.xlsx: equity / government bond volatility; CRP / this = country
                            # default spread added to the cost of debt


class ValuationError(Exception):
    """The company cannot be valued with the corporate toolkit (a missing key line, say)."""


@dataclass(frozen=True)
class IndustryData:
    name: str
    how: str
    unlevered_beta: Value | None
    operating_margin: Value | None
    revenue_growth: Value | None
    sales_to_capital: Value | None


@dataclass
class EngineInputs:
    ticker: str
    name: str
    sic: str
    valuation_date: date
    historicals: Historicals            # in US$ (FX-converted when needed)
    analysis: Analysis
    price: Value
    basic_shares: Value
    adr_ratio: float
    market_cap: Value
    risk_free: Value
    erp: Value
    beta_regression: Value | None
    industry: IndustryData
    crp: Value
    marginal_tax: Value
    rating_table_large: list[dict]
    rating_table_small: list[dict]
    consensus: list[ConsensusYear] = field(default_factory=list)
    segments: list[Segment] = field(default_factory=list)
    overrides: dict = field(default_factory=dict)


@dataclass
class Valuation:
    classification: Classification
    cycle: dict
    wacc: WaccResult
    cost_of_debt_detail: dict
    plan: ForecastPlan
    dcf_inputs: DCFInputs | None
    dcf: DCFResult | None
    scenarios: list[ScenarioResult]
    scenario_value: float | None        # probability-weighted value per US share
    structural_case: DCFResult | None   # cyclical companies: current margins held
    sensitivity_wacc_growth: dict | None
    sensitivity_growth_margin: dict | None
    reverse: dict | None
    sotp: SOTPResult
    diluted_shares: Value
    bridge: list[tuple[str, Value]]
    asset_value_per_share: Value | None  # declining companies: tangible book cross-check
    flags: list[Flag]
    per_us_share_factor: float          # ADR ratio: value per ordinary share x this = value per US share

    def per_us_share(self, x: float | None) -> float | None:
        return None if x is None else x * self.per_us_share_factor


def _latest(h: Historicals, line: str) -> Value | None:
    for p in reversed([x.label for x in h.periods]):
        v = h.get(line, p)
        if v is not None and v.value is not None:
            return v
    return None


def _neg(v: Value, name: str) -> Value:
    return calc(lambda x: -x, f"minus {name}", v.period, MILLIONS, v.currency, **{name: v})


def value_company(i: EngineInputs) -> Valuation:
    h, a = i.historicals, i.analysis
    flags: list[Flag] = []
    last = h.fy_labels[-1]
    cur_p = h.ltm.label if h.ltm and h.v("revenue", h.ltm.label) else last
    missing = [x for x in ("revenue", "operating_income") if h.v(x, cur_p) is None]
    if missing or not h.v("revenue", cur_p):
        raise ValuationError(f"Cannot run the DCF: {' and '.join(missing) or 'revenue'} not available for {cur_p}.")
    cur_margin = calc(lambda o, r: o / r, f"operating income / revenue ({cur_p})", cur_p, RATIO, None,
                      operating_income=h.get("operating_income", cur_p), revenue=h.get("revenue", cur_p))
    cls = classify(h, i.sic, cur_margin.value)
    if i.overrides.get("stage"):
        from dataclasses import replace
        cls = replace(cls, stage=i.overrides["stage"], override=i.overrides.get("stage_reason", "override"))
    cyc = cycle_position(h, cur_margin.value)
    if cyc.get("above_90th"):
        flags.append(Flag(AMBER, "margin_above_90th", "Margins near a 10-year high (possible cyclical peak)",
                          f"Current operating margin {cyc['current_margin']:.1%} is at the "
                          f"{cyc['percentile']:.0%} percentile of the last {cyc['years']} years "
                          f"(range {cyc['min_margin']:.1%} to {cyc['max_margin']:.1%}).", cur_p,
                          {"percentile": cyc["percentile"], "current_margin": cyc["current_margin"]}))

    # --- balance sheet for the bridge: latest reported -----------------------------------------------------
    bs_p = cur_p
    debt = _latest(h, "debt_for_valuation") or Value(0.0, "USD", MILLIONS, bs_p, "assumed zero")
    bs_date = next(p.end for p in h.periods if p.label == bs_p)
    cash = _latest(h, "cash_and_investments") or Value(0.0, "USD", MILLIONS, bs_p, "assumed zero")
    minority = _latest(h, "minority_interest")
    preferred = _latest(h, "preferred_equity")
    bridge: list[tuple[str, Value]] = [("Debt", _neg(debt, "debt")), ("Cash and investments", cash)]
    if minority is not None and minority.value:
        bridge.append(("Minority interests", _neg(minority, "minority_interest")))
    if preferred is not None and preferred.value:
        bridge.append(("Preferred equity", _neg(preferred, "preferred_equity")))

    # --- WACC ----------------------------------------------------------------------------------------------
    interest_cover = a.m("interest_cover", cur_p) or a.m("interest_cover", last)
    large = (i.market_cap.value or 0) >= LARGE_FIRM_MCAP
    table = i.rating_table_large if large else i.rating_table_small
    rating = dict(synthetic_rating(interest_cover, table))
    net_cash = (cash.value or 0) > (debt.value or 0)
    floor = next((r for r in table if r["rating"] == NET_CASH_RATING_FLOOR), None)
    if net_cash and floor and rating["spread"] > floor["spread"]:
        rating = {**floor, "rating": f"{floor['rating']} (floor: the company holds net cash; synthetic rating from "
                                     f"interest cover was {rating['rating']})"}
    spread = Value(rating["spread"], None, RATIO, "current", "Damodaran ratings.xls",
                   note=f"synthetic rating {rating['rating']} from interest cover "
                        f"{'n/a' if interest_cover is None else f'{interest_cover:.1f}x'} "
                        f"({'large' if large else 'small'}-firm table)")
    country_spread = calc(lambda c: c / RELATIVE_EQUITY_VOL, "CRP / relative equity volatility (1.52)", "current",
                          RATIO, None, crp=i.crp)
    kd = calc(lambda rf, s, cs: rf + s + cs, "risk-free + company default spread + country default spread",
              "current", RATIO, None, risk_free=i.risk_free, default_spread=spread, country_spread=country_spread)
    if interest_cover is None and (debt.value or 0) > 0:
        flags.append(Flag(AMBER, "interest_not_reported", "Interest expense not reported",
                          f"The company has debt of {debt.value:,.0f}m but no tagged interest expense, so the "
                          f"synthetic rating defaults to {rating['rating']}. Check the cost of debt.", None,
                          {"debt": debt.value}))
    w = compute_wacc(WaccInputs(i.risk_free, i.erp, i.beta_regression, i.industry.unlevered_beta, i.marginal_tax,
                                i.crp, kd, i.market_cap, debt, beta_choice=i.overrides.get("beta_choice", "industry"),
                                beta_override=i.overrides.get("beta")))
    wacc = i.overrides.get("wacc", w.wacc.value)
    if not 0.06 <= wacc <= 0.15:
        flags.append(Flag(AMBER, "wacc_range", "WACC outside 6-15%", f"WACC is {wacc:.2%}.", None, {"wacc": wacc}))

    # --- forecast ----------------------------------------------------------------------------------------------
    margins_5y = sorted(h.v("operating_income", p) / h.v("revenue", p) for p in h.fy_labels[-5:]
                        if h.v("operating_income", p) is not None and h.v("revenue", p))
    plan = build_plan(
        h, cls.stage, valuation_date=i.valuation_date, current_margin=cur_margin, consensus=i.consensus,
        industry_margin=i.industry.operating_margin, industry_growth=i.industry.revenue_growth,
        industry_sales_to_capital=i.industry.sales_to_capital,
        effective_tax=a.metrics.get("effective_tax_rate", {}).get(last), marginal_tax=i.marginal_tax,
        risk_free=i.risk_free, wacc=wacc, roic=a.metrics.get("roic", {}).get(last),
        mid_cycle_margin=cyc.get("mid_cycle_margin"), five_year_avg_margin=median(margins_5y) if margins_5y else None,
        overrides=i.overrides)
    flags += plan.flags
    g = plan.terminal_growth.value
    if g >= i.risk_free.value or g > 0.04:
        flags.append(Flag(AMBER, "terminal_growth_high", "Terminal growth high",
                          f"Terminal growth {g:.2%} is at or above the risk-free rate ({i.risk_free.value:.2%}) or above 4%.",
                          None, {"terminal_growth": g, "risk_free": i.risk_free.value}))

    # --- shares and DCF ----------------------------------------------------------------------------------------
    eps_dil = None
    for p in reversed([x.label for x in h.periods]):
        dw, bw = h.get("shares_diluted_weighted", p), h.get("shares_basic_weighted", p)
        if dw is not None and bw is not None and dw.value is not None and bw.value is not None:
            eps_dil = calc(lambda d, b: d - b, f"diluted - basic weighted shares ({p})", p, SHARES_M, None,
                           diluted=dw, basic=bw)
            break
    ordinary_price = calc(lambda p, k: p / k, "US share price / ADR ratio", "current", PER_SHARE, "USD",
                          price=i.price, adr_ratio=Value(i.adr_ratio, None, "ratio", "current", "ADR ratio"))
    shares = diluted_shares(i.basic_shares, ordinary_price, _latest(h, "rsus_outstanding"),
                            _latest(h, "options_outstanding"), _latest(h, "options_strike"), eps_dil)
    bridge_t = tuple((name, v.value) for name, v in bridge)
    dcf_inputs = dcf = None
    scen, scen_value, structural = [], None, None
    sens1 = sens2 = rev = None
    try:
        dcf_inputs = to_dcf_inputs(plan, wacc, bridge_t, shares.value, balance_sheet_date=bs_date)
        dcf = run_dcf(dcf_inputs)
        g_cap = 0.0 if cls.stage == DECLINING else i.risk_free.value
        scen, scen_value = run_scenarios(dcf_inputs, DEFAULT_SCENARIOS, max_terminal_growth=g_cap)
        sens1, sens2 = grid_wacc_growth(dcf_inputs), grid_growth_margin(dcf_inputs)
        rev = reverse_dcf(dcf_inputs, ordinary_price.value)
        if cls.stage == CYCLICAL:
            from dataclasses import replace
            held = tuple(replace(y, operating_margin=cur_margin.value) for y in dcf_inputs.years)
            structural = run_dcf(replace(dcf_inputs, years=held, terminal_margin=cur_margin.value))
    except DCFError as exc:
        flags.append(Flag(HARD_STOP, "dcf_invalid", "DCF cannot be computed", str(exc), None, {}))
    if dcf is not None and dcf.tv_share_of_ev > 0.80:
        flags.append(Flag(AMBER, "tv_share_high", "Terminal value above 80% of EV",
                          f"Terminal value is {dcf.tv_share_of_ev:.0%} of enterprise value.", None,
                          {"tv_share": dcf.tv_share_of_ev}))

    sotp = run_sotp(i.segments, sum(bridge_t), shares.value) if i.segments else \
        SOTPResult(False, "no segment revenue and profit data yet (the research desk extracts it from the annual report)")

    asset_value = None
    if cls.stage == DECLINING:
        pe, gw, it = _latest(h, "parent_equity"), _latest(h, "goodwill"), _latest(h, "intangibles")
        if pe is not None:
            zero = Value(0.0, "USD", MILLIONS, pe.period, "assumed zero")
            tb = calc(lambda e, g_, x: e - g_ - x, "shareholders' equity - goodwill - intangibles", pe.period,
                      MILLIONS, "USD", equity=pe, goodwill=gw or zero, intangibles=it or zero)
            asset_value = calc(lambda t, s: t / s, "tangible book value / diluted shares", pe.period, PER_SHARE, "USD",
                               tangible_book=tb, shares=shares)

    return Valuation(cls, cyc, w, {"interest_cover": interest_cover, **rating, "large_firm": large,
                                   "pre_tax_cost_of_debt": kd}, plan, dcf_inputs, dcf, scen, scen_value, structural,
                     sens1, sens2, rev, sotp, shares, bridge, asset_value, flags, i.adr_ratio)
