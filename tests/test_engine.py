"""Valuation engine unit tests: DCF conventions, WACC, scenarios, sensitivity, reverse DCF, SOTP, shares,
forecast rules, and the KO / cyclical golden tests on recorded filings with synthetic market inputs."""
from dataclasses import replace
from datetime import date

import pytest

from engine.analysis import analyse
from engine.classify import CYCLICAL, EARLY, MATURE_STABLE, classify, cycle_position, toolkit_for_sic
from engine.dcf import Conventions, DCFError, DCFInputs, YearDrivers, run_dcf, with_changes
from engine.forecast import ConsensusYear, build_plan
from engine.scenarios import DEFAULT_SCENARIOS, grid_growth_margin, grid_wacc_growth, reverse_dcf, run_scenarios
from engine.shares import diluted_shares
from engine.sotp import Segment, applicability, run_sotp
from engine.valuation import EngineInputs, IndustryData, value_company
from engine.values import MILLIONS, PER_SHARE, RATIO, SHARES_M, Value
from engine.wacc import WaccInputs, compute_wacc, synthetic_rating
from tests.conftest import historicals_for


def r(x, unit=RATIO):
    return Value(x, None, unit, "test", "test")


def simple(years=3, conv=Conventions(), **kw) -> DCFInputs:
    ys = years if isinstance(years, tuple) else         tuple(YearDrivers(f"FY{2026 + k}E", 0.10, 0.20, 0.25, sales_to_capital=2.0) for k in range(years))
    base = dict(base_label="FY2025", base_revenue=1000.0, years=ys, wacc=0.09, terminal_growth=0.03,
                terminal_roic=0.15, stub_fraction=1.0, conventions=conv, bridge=(("debt", -100.0),), shares=10.0)
    base.update(kw)
    return DCFInputs(**base)


# --- DCF -------------------------------------------------------------------------------------------------
def test_mid_year_periods_with_stub():
    res = run_dcf(simple(conv=Conventions(discounting="mid_year", stub=True), stub_fraction=0.25))
    assert [y.period for y in res.years] == pytest.approx([0.125, 0.75, 1.75])
    # Gordon TV is as at one period before FCF_{N+1}: mid-year N under mid-year discounting
    assert res.terminal_period == pytest.approx(1.75)
    assert res.years[0].counted_fcf == pytest.approx(res.years[0].fcf * 0.25)


def test_end_year_periods_without_stub():
    res = run_dcf(simple(conv=Conventions(discounting="end_year", stub=False), stub_fraction=0.25))
    assert [y.period for y in res.years] == [1, 2, 3] and res.terminal_period == 3


def test_value_driver_terminal_reinvestment_consistent_with_growth():
    inp = simple()
    res = run_dcf(inp)
    last = res.years[-1]
    nopat_next = last.revenue * 1.03 * 0.20 * (1 - 0.25)
    assert res.terminal_fcf == pytest.approx(nopat_next * (1 - 0.03 / 0.15))   # reinvestment rate = g / ROIC
    assert res.terminal_value == pytest.approx(res.terminal_fcf / (0.09 - 0.03))


def test_terminal_growth_at_or_above_wacc_is_rejected():
    with pytest.raises(DCFError, match="at or above WACC"):
        run_dcf(simple(terminal_growth=0.09))


def test_sbc_as_cash_on_adjusted_margins():
    ys = tuple(replace(y, sbc_pct=0.05) for y in simple().years)
    no_sbc = run_dcf(simple(conv=Conventions(margin_basis="adjusted", sbc_as_cash=True)))
    with_sbc = run_dcf(replace(simple(conv=Conventions(margin_basis="adjusted", sbc_as_cash=True)), years=ys))
    ignore = run_dcf(replace(simple(conv=Conventions(margin_basis="adjusted", sbc_as_cash=False)), years=ys))
    assert with_sbc.years[0].sbc_cost == pytest.approx(with_sbc.years[0].revenue * 0.05)
    assert with_sbc.value_per_share < ignore.value_per_share
    assert ignore.value_per_share == pytest.approx(no_sbc.value_per_share)  # ignoring SBC = no SBC at all


def test_equity_bridge_and_per_share():
    res = run_dcf(simple())
    assert res.equity_value == pytest.approx(res.enterprise_value - 100)
    assert res.value_per_share == pytest.approx(res.equity_value / 10)


# --- WACC -------------------------------------------------------------------------------------------------
def test_relevered_beta_and_wacc():
    w = compute_wacc(WaccInputs(r(0.04), r(0.05), r(1.3), r(0.8), r(0.25), r(0.01), r(0.06),
                                Value(800, "USD", MILLIONS, "t", "t"), Value(200, "USD", MILLIONS, "t", "t")))
    beta = 0.8 * (1 + 0.75 * 0.25)
    assert w.beta.value == pytest.approx(beta)
    ke = 0.04 + beta * 0.05 + 0.01
    assert w.cost_of_equity.value == pytest.approx(ke)
    assert w.wacc.value == pytest.approx(0.8 * ke + 0.2 * 0.06 * 0.75)
    assert any("unlevered beta" in line for line in w.wacc.trace())


def test_synthetic_rating_bands():
    table = [{"min": -1e5, "max": 0.799999, "rating": "C", "spread": 0.16},
             {"min": 0.8, "max": 8.499999, "rating": "A", "spread": 0.01},
             {"min": 8.5, "max": 1e5, "rating": "AAA", "spread": 0.004}]
    assert synthetic_rating(10, table)["rating"] == "AAA"
    assert synthetic_rating(2, table)["rating"] == "A"
    assert synthetic_rating(None, table)["rating"].startswith("not rated")


# --- scenarios, sensitivity, reverse DCF ---------------------------------------------------------------
def test_scenarios_weighted_and_ordered():
    results, weighted = run_scenarios(simple())
    bear, base, bull = (x.value_per_share for x in results)
    assert bear < base < bull
    assert weighted == pytest.approx(0.25 * bear + 0.5 * base + 0.25 * bull)
    assert DEFAULT_SCENARIOS[0].describe().startswith("revenue growth -3 points")


def test_sensitivity_centre_is_base():
    inp = simple()
    base = run_dcf(inp).value_per_share
    assert grid_wacc_growth(inp)["value_per_share"][2][2] == pytest.approx(base)
    assert grid_growth_margin(inp)["value_per_share"][2][2] == pytest.approx(base)


def test_reverse_dcf_recovers_price():
    inp = simple()
    target = run_dcf(replace(inp, years=tuple(replace(y, revenue_growth=y.revenue_growth + 0.05)
                                              for y in inp.years))).value_per_share
    out = reverse_dcf(inp, target)
    assert out["growth"]["solved"] and out["growth"]["growth_shift"] == pytest.approx(0.05, abs=1e-4)
    m_target = run_dcf(with_changes(inp, margin_shift=0.03)).value_per_share
    out = reverse_dcf(inp, m_target)
    assert out["margin"]["implied_terminal_margin"] == pytest.approx(0.23, abs=1e-4)


def test_reverse_dcf_unreachable_price_reported():
    out = reverse_dcf(simple(), 1e9)
    assert not out["growth"]["solved"] and "not reachable" in out["growth"]["reason"]


def test_losses_pay_no_tax_and_carry_forward():
    ys = (YearDrivers("Y1", 0.0, -0.10, 0.25, sales_to_capital=2.0), YearDrivers("Y2", 0.0, 0.15, 0.25, sales_to_capital=2.0))
    res = run_dcf(simple(conv=Conventions(stub=False), years=ys))
    y1, y2 = res.years
    assert y1.taxes == 0 and y1.nopat == pytest.approx(-100)
    assert y2.loss_carryforward_used == pytest.approx(100)
    assert y2.taxes == pytest.approx((150 - 100) * 0.25)


def test_negative_terminal_profit_rejected():
    ys = (YearDrivers("Y1", 0.1, -0.05, 0.25, sales_to_capital=2.0),)
    with pytest.raises(DCFError, match="terminal operating profit"):
        run_dcf(simple(years=ys))


def test_bear_below_bull_for_loss_makers():
    ys = tuple(YearDrivers(f"Y{k}", 0.2, m, 0.25, sales_to_capital=2.0) for k, m in enumerate((-0.2, -0.05, 0.08)))
    results, _ = run_scenarios(simple(years=ys))
    bear, base, bull = (x.value_per_share for x in results)
    assert bear < base < bull


def test_one_year_horizon_terminal_timing():
    res = run_dcf(simple(years=1, conv=Conventions(discounting="end_year", stub=True), stub_fraction=0.25))
    assert res.terminal_period == pytest.approx(0.25)


def test_explicit_timing_counts_cash_after_balance_sheet():
    from engine.forecast import year_timing
    # balance sheet 30 Jun, valuation 14 Oct, year ends 31 Dec: half the year counted, part already earned
    pre, post, t = year_timing(date(2026, 1, 1), date(2026, 12, 31), date(2026, 6, 30), date(2026, 10, 14), True)
    assert pre + post == pytest.approx(184 / 364, abs=1e-3)
    assert pre == pytest.approx(106 / 364, abs=1e-3) and t == pytest.approx(78 / 2 / 365.25, abs=1e-3)


# --- SOTP and shares ---------------------------------------------------------------------------------------
def test_sotp_applicability_and_value():
    segs = [Segment("Deliveries", 600, 60, multiple=1.5, metric_value=600, multiple_source="peers"),
            Segment("Financial services", 300, -60, multiple=2.0, metric_value=300, multiple_source="peers")]
    ok, why = applicability(segs)
    assert ok and "margins" in why
    res = run_sotp(segs, bridge=100, shares=10)
    assert res.enterprise_value == pytest.approx(1500) and res.value_per_share == pytest.approx(160)
    same = [Segment("A", 500, 50), Segment("B", 500, 52)]
    assert applicability(same)[0] is False


def test_treasury_method():
    basic, price = Value(100, None, SHARES_M, "t", "t"), Value(50, "USD", PER_SHARE, "t", "t")
    out = diluted_shares(basic, price, rsus=Value(2, None, SHARES_M, "t", "t"),
                         options=Value(10, None, SHARES_M, "t", "t"), strike=Value(40, "USD", PER_SHARE, "t", "t"))
    assert out.value == pytest.approx(100 + 2 + 10 * (1 - 40 / 50))
    proxy = diluted_shares(basic, price, eps_dilution=Value(3, None, SHARES_M, "t", "t"))
    assert proxy.value == 103 and "EPS calculation" in proxy.note


# --- classification and forecast rules -------------------------------------------------------------------
def test_toolkits_from_sic():
    assert toolkit_for_sic("6021")[0] == "bank"
    assert toolkit_for_sic("6331")[0] == "insurer"
    assert toolkit_for_sic("6798")[0] == "reit"
    assert toolkit_for_sic("2080")[0] == "corporate"


def test_ko_is_mature_stable():
    """Golden test 5."""
    c = classify(historicals_for("KO"), "2080")
    assert c.stage == MATURE_STABLE, c.stage_reason


def test_cyclical_classified_and_normalised():
    """Golden test 6: MU is cyclical and its forecast margins normalise to the mid-cycle margin."""
    h = historicals_for("MU")
    a = analyse(h)
    c = classify(h, "3674")
    assert c.stage == CYCLICAL, c.stage_reason
    last = h.fy_labels[-1]
    cur = h.v("operating_income", last) / h.v("revenue", last)
    cyc = cycle_position(h, cur)
    assert cyc["above_90th"] and cyc["mid_cycle_margin"] < cur
    plan = _plan(h, a, c.stage, cur, cyc["mid_cycle_margin"])
    margins = plan.path("operating_margin")
    assert margins[:2] == pytest.approx([cur, cur])
    assert margins[2:] == pytest.approx([cyc["mid_cycle_margin"]] * (len(margins) - 2))
    growth = plan.path("revenue_growth")
    assert growth[0] <= 0.10  # a cyclical's peak-year growth is not extrapolated


def test_grab_is_early_stage():
    assert classify(historicals_for("GRAB"), "7389").stage == EARLY


def _plan(h, a, stage, cur_margin, mid=None, consensus=(), valuation_date=date(2026, 10, 14)):
    return build_plan(h, stage, valuation_date=valuation_date, current_margin=r(cur_margin),
                      consensus=list(consensus), industry_margin=r(0.15), industry_growth=r(0.06),
                      industry_sales_to_capital=r(1.5), effective_tax=r(0.2), marginal_tax=r(0.25),
                      risk_free=r(0.045), wacc=0.09, roic=r(0.2), mid_cycle_margin=mid, five_year_avg_margin=0.2)


def test_consensus_used_only_with_three_analysts_and_flagged_above_history():
    h = historicals_for("UBER")
    a = analyse(h)
    fy25 = h.v("revenue", "FY2025")
    # +100%: above Uber's best year in the last decade (FY2022, +83%)
    cons = [ConsensusYear(date(2026, 12, 31), fy25 * 2.0, fy25 * 1.9, fy25 * 2.1, None, 12, "test"),
            ConsensusYear(date(2027, 12, 31), fy25 * 2.0 * 1.10, 0, 0, None, 12, "test")]
    plan = _plan(h, a, "high_growth", 0.1, consensus=cons)
    assert plan.path("revenue_growth")[0] == pytest.approx(1.0)
    assert any(f.code == "consensus_above_history" for f in plan.flags)
    few = [replace(c, analysts=2) for c in cons]
    plan2 = _plan(h, a, "high_growth", 0.1, consensus=few)
    assert plan2.path("revenue_growth")[0] == pytest.approx(52017 / 43978 - 1)
    assert "history" in plan2.drivers["revenue_growth"].source


def test_completed_unreported_year_is_skipped():
    h = historicals_for("AAPL")  # FY2025 ended Sep 2025; FY2026 ended Sep 2026, unreported on 14 Oct 2026
    plan = _plan(h, analyse(h), MATURE_STABLE, 0.3)
    assert plan.skipped == ["FY2026E"] and plan.labels[1] == "FY2027E"
    assert 0.9 < plan.stub_fraction < 1.0


# --- full valuation with synthetic market inputs --------------------------------------------------------
def test_value_company_end_to_end_ko():
    h = historicals_for("KO")
    a = analyse(h)
    m = lambda x: Value(x, "USD", MILLIONS, "t", "t")  # noqa: E731
    table = [{"min": -1e5, "max": 1e5, "rating": "AA", "spread": 0.006}]
    i = EngineInputs("KO", "Coca-Cola", "2080", date(2026, 10, 14), h, a, Value(90, "USD", PER_SHARE, "t", "t"),
                     Value(4300, None, SHARES_M, "t", "t"), 1.0, m(387000), r(0.045), r(0.045), r(0.6),
                     IndustryData("Beverage (Soft)", "test", r(0.55), r(0.2), r(0.05), r(1.5)), r(0.005), r(0.25),
                     table, table)
    v = value_company(i)
    assert v.classification.stage == MATURE_STABLE
    assert v.dcf is not None and v.dcf.value_per_share > 0
    assert v.scenario_value is not None
    assert {name for name, _ in v.bridge} >= {"Debt", "Cash and investments"}
    # US GAAP: operating leases are not in valuation debt (their cost is already in operating income)
    debt = dict(v.bridge)["Debt"].value
    assert -debt == pytest.approx(h.v("debt_for_valuation", h.ltm.label))
    assert -debt < h.v("total_debt_incl_leases", h.ltm.label)
    # cash generated after the latest balance sheet (3 Apr 2026) is counted
    assert v.dcf.inputs.timing[0][0] > 0.4
    assert 0.05 < v.wacc.wacc.value < 0.10
