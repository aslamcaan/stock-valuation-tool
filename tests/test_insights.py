"""Explaining the valuation: walk to the price, what the price pays for, Monte Carlo range, peer regressions."""
from dataclasses import replace

import pytest

from engine.comps import CompanyMetrics
from engine.dcf import run_dcf
from engine.insights import (SPREADS, monte_carlo, peer_regressions, price_walk, value_split)
from engine.scenarios import DEFAULT_SCENARIOS
from tests.test_engine import simple


def test_walk_starts_at_our_dcf_ends_at_the_price_and_adds_up():
    inp = simple(years=5, terminal_tax_rate=0.25, terminal_growth=0.025)
    base = run_dcf(inp).value_per_share
    price = base * 1.8
    steps = price_walk(inp, price, effective_tax=0.18, current_roic=0.30, current_margin=0.24, risk_free=0.045)
    assert steps[0]["value"] == pytest.approx(base)
    assert steps[-1]["value"] == pytest.approx(price, rel=1e-4)
    assert sum(s["change"] for s in steps) == pytest.approx(price - base, rel=1e-6)  # the bars add up to the gap
    labels = [s["label"] for s in steps]
    assert labels[1:] == ["Today's margin held", "Own tax rate", "Today's ROIC held", "3% terminal growth",
                          "Discount rate the price needs"]
    assert all(s["change"] > 0 for s in steps[1:-1])  # each convention is applied only where more generous


def test_walk_below_our_value_only_needs_a_higher_discount_rate():
    inp = simple(years=5, terminal_tax_rate=0.25)
    base = run_dcf(inp).value_per_share
    steps = price_walk(inp, base * 0.7, effective_tax=0.18, current_roic=0.30, current_margin=0.24, risk_free=0.045)
    assert [s["label"] for s in steps] == ["Our DCF", "Discount rate the price needs"]
    assert "instead of 9.0%" in steps[1]["detail"] and steps[1]["change"] < 0


def test_walk_says_when_the_price_is_out_of_reach():
    inp = simple(years=5)
    steps = price_walk(inp, run_dcf(inp).value_per_share * 1000, None, None, None, risk_free=0.045)
    assert steps[-1]["label"] == "Not explained"


def test_value_split_adds_up_and_measures_the_market_growth_premium():
    inp = simple(years=5)
    d = run_dcf(inp)
    sp = value_split(d, price=d.value_per_share * 2)
    nopat = 1000 * 0.20 * 0.75
    assert sp["no_growth_ev"] == pytest.approx(nopat / 0.09)
    assert sp["no_growth_ev"] + sp["growth_ev"] == pytest.approx(d.enterprise_value)
    assert sp["pv_forecast"] + sp["pv_terminal"] == pytest.approx(d.enterprise_value)
    assert sp["market_ev"] == pytest.approx(d.value_per_share * 2 * 10 + 100)  # price x shares + debt
    assert sp["market_growth_ev"] == pytest.approx(sp["market_ev"] - sp["no_growth_ev"])


def test_value_split_needs_positive_operating_profit():
    inp = simple(years=3)
    loss = replace(inp, years=tuple(replace(y, operating_margin=-0.05) for y in inp.years), terminal_margin=0.10)
    assert value_split(run_dcf(loss), 10.0) is None


def test_monte_carlo_is_repeatable_and_centred_on_the_base_case():
    inp = simple(years=5)
    base = run_dcf(inp).value_per_share
    a, b = monte_carlo(inp, price=base, n=1500), monte_carlo(inp, price=base, n=1500)
    assert a["pct"] == b["pct"]  # fixed seed: the same range on every run
    assert a["pct"][10] < base < a["pct"][90]
    assert abs(a["pct"][50] / base - 1) < 0.05
    assert 0.35 < a["prob_above_price"] < 0.65
    bear, _, bull = DEFAULT_SCENARIOS  # each input's 10th-90th percentile range is the bear-bull step
    assert SPREADS["growth"] * 2 * 1.2816 == pytest.approx(bull.growth_shift - bear.growth_shift)


def _co(t, margin, growth, ev_sales, ev_ebitda=None):
    rev = 1000.0
    m = CompanyMetrics(t, t, "2080", ev_sales * rev, 10.0, rev, (ev_ebitda and ev_sales * rev / ev_ebitda) or None,
                       100.0, 50.0, None, 0.0, 0.0, operating_income=margin * rev,
                       benchmarks={"operating_margin": margin, "revenue_growth": growth})
    return m


def test_peer_regression_gives_a_higher_multiple_to_a_more_profitable_company():
    # peers on an exact line EV/Sales = 1 + 20 x margin; the company earns 25%
    peers = [_co(f"P{k}", m, 0.05, 1 + 20 * m) for k, m in enumerate((0.05, 0.10, 0.12, 0.15, 0.20))]
    me = _co("ME", 0.25, 0.05, 4.0)
    reg = {r["key"]: r for r in peer_regressions(me, peers, shares=100.0, bridge=0.0)}
    r = reg["ev_sales"]
    assert r["applicable"] and r["r2"] == pytest.approx(1.0)
    assert r["warranted"] == pytest.approx(6.0) and r["extrapolated"]  # 25% is above every peer's margin
    assert r["implied_price"] == pytest.approx(6.0 * 1000 / 100)
    assert not reg["ev_ebitda"]["applicable"]  # no EBITDA given


def test_peer_regression_needs_five_peers():
    peers = [_co(f"P{k}", m, 0.05, 1 + 20 * m) for k, m in enumerate((0.05, 0.10, 0.15))]
    r = peer_regressions(_co("ME", 0.12, 0.05, 3.0), peers, 100.0, 0.0)[0]
    assert not r["applicable"] and "needs 5 peers" in r["reason"]


def test_growth_margin_correlation_from_history():
    from engine.insights import growth_margin_correlation
    line = [(g / 100, g / 400) for g in (2, 5, 8, 3, 10, 6)]  # margin change = growth / 4 every year
    c = growth_margin_correlation(line)
    assert c["raw"] == pytest.approx(1.0) and c["rho"] == 0.8 and c["n"] == 6  # capped: six years is not certainty
    assert growth_margin_correlation(line[:5]) is None  # too few years
    assert growth_margin_correlation([(0.05, m) for _, m in line]) is None  # no variation in growth


def test_correlated_draws_widen_the_range_when_growth_and_margin_move_together():
    inp = simple(years=5)
    base = run_dcf(inp).value_per_share
    ind, cor = monte_carlo(inp, base, n=1500), monte_carlo(inp, base, n=1500, growth_margin_corr=0.8)
    assert monte_carlo(inp, base, n=1500, growth_margin_corr=0.0)["pct"] == ind["pct"]  # 0 = the independent draws
    assert cor["pct"][90] - cor["pct"][10] > ind["pct"][90] - ind["pct"][10]
    assert cor["growth_margin_corr"] == 0.8


def test_dividend_check_by_hand():
    from engine.insights import dividend_check
    from tests.engine_fixtures import engine_inputs
    from engine.valuation import value_company
    v = value_company(engine_inputs("GRAB"))
    dcf = v.dcf
    inp = dcf.inputs
    y1 = inp.years[0]
    n0 = inp.base_revenue * y1.operating_margin * (1 - y1.tax_rate)
    if n0 <= 0:
        pytest.skip("fixture has no positive NOPAT")
    price, dps, coe, g = 10.0, 0.30, 0.09, 0.025
    d = dividend_check(dcf, dps, coe, g, price)
    divs = [dps * max(y.nopat, 0) / n0 for y in dcf.years]
    pv = sum(x * (1 + coe) ** -(t + 1) for t, x in enumerate(divs))
    tv = divs[-1] * (1 + g) / (coe - g) * (1 + coe) ** -len(divs)
    assert d["value"] == pytest.approx(pv + tv)
    assert d["implied_growth"] == pytest.approx((price * coe - dps) / (price + dps))
    # Gordon check: at the implied growth, a flat model gives back the price
    gi = d["implied_growth"]
    assert dps * (1 + gi) / (coe - gi) == pytest.approx(price)
    assert dividend_check(dcf, 0.05, coe, g, price) is None   # 0.5% yield: too small to say much
    assert dividend_check(dcf, dps, 0.02, g, price) is None   # CoE below growth
