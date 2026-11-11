"""Regression tests for the 9 Nov 2026 runs (PLTR, MU, AMD, INTC, SHOP, NVDA, SNDK).

Each test is named after the ticker whose report showed the problem and uses that report's own figures. They are
offline: the recorded filings of those companies are not in the fixtures, so the cases are rebuilt from the numbers in
the reports (the live re-run of all seven is in PLAN.md).
"""
from datetime import date, datetime, timezone
from types import SimpleNamespace

import pytest

from core.cache import Cached
from data_desk import checks
from data_desk.peers import PEER_BLOCKLIST, is_true_peer, peer_group
from datasources.market import MarketData
from desks.dcf_guard import drop_wrong_dcf
from desks.modelling import top_notes
from desks.pipeline import apply_headline_review
from desks.review import headline_challenge
from engine.classify import CYCLICAL, HIGH_GROWTH, EARLY, classify, cycle_position
from engine.comps import CompanyMetrics, mid_cycle_metrics, run_comps
from engine.dcf import DCFInputs, YearDrivers, run_dcf
from engine.flags import RED, Flag
from engine.forecast import build_plan, fade_growth
from engine.insights import price_walk
from engine.model import Historicals, Period
from engine.rubric import gate_by_evidence
from engine.valuation import fit_failure
from engine.values import MILLIONS, RATIO, Value
from engine.verdict import MAX_COMPONENT_SPREAD, Verdict, blend, confidence, fall_back_to_dcf
from tests.conftest import historicals_for


def hist(revenue: list[float], op_inc: list[float], fcf: list[float] | None = None) -> Historicals:
    """A synthetic history: fiscal years ending 31 December, ending 2025."""
    n = len(revenue)
    labels = [f"FY{2026 - n + k}" for k in range(n)]
    periods = [Period(lab, date(2026 - n + k, 12, 31), date(2025 - n + k, 12, 31), "FY") for k, lab in enumerate(labels)]
    mk = lambda xs: {lab: Value(x, "USD", MILLIONS, lab, "test") for lab, x in zip(labels, xs)}  # noqa: E731
    lines = {"revenue": mk(revenue), "operating_income": mk(op_inc)}
    if fcf is not None:
        lines["fcf"] = mk(fcf)
    return Historicals("USD", "us-gaap", periods, lines)


def r(x):
    return Value(x, None, RATIO, "test", "test")


# --- Priority 1: the headline must not contradict the review desk -------------------------------------------------------
def test_MU_blend_is_not_used_when_the_methods_disagree_by_more_than_3x():
    """MU: DCF $431.86 against comps $2,717 and history $2,830 blended to a 'Strong Buy' at $2,338."""
    v = blend({"dcf": 431.86, "comps": 2717.0, "history": 2830.0}, price=900.0)
    assert v.fallback == "components_diverge"
    assert v.fair_value == pytest.approx(431.86)         # the scenario-weighted DCF, not the blend
    assert v.blend_fair_value is not None and v.blend_fair_value > 1500
    assert v.verdict == "Overvalued" and "6." in v.headline_note  # the spread is stated
    level, reasons = confidence(v, estimate_dispersion=0.05, red_flags=0, amber_flags=0, tv_share=0.5, completeness=1.0)
    assert level == "Low" and "disagree" in reasons[0]


def test_SNDK_blend_is_blocked_too():
    v = blend({"dcf": 700.0, "comps": 2890.0, "history": 3100.0}, price=835.06)
    assert v.fallback == "components_diverge" and v.fair_value == pytest.approx(700.0)


def test_PLTR_blend_of_comps_34_dcf_400_history_285_is_blocked():
    v = blend({"dcf": 399.52, "comps": 34.11, "history": 284.72}, price=190.0)
    assert v.fallback == "components_diverge" and v.fair_value == pytest.approx(399.52)


def test_methods_within_3x_still_blend():
    v = blend({"dcf": 100.0, "comps": 150.0, "history": 200.0}, price=120.0)
    assert v.fallback is None and v.fair_value == pytest.approx(0.5 * 100 + 0.3 * 150 + 0.2 * 200)
    assert MAX_COMPONENT_SPREAD == 3.0


def _model(verdict: Verdict, dcf_weighted: float | None):
    return SimpleNamespace(verdict=verdict, trace={}, valuation=SimpleNamespace(
        dcf_figures={"probability_weighted": dcf_weighted}, model_fit_failed=False))


def test_MU_review_desk_saying_discard_takes_the_headline_off_the_blend():
    review = {"challenges": [{"assumption": "Fair value blend", "severity": "high",
                              "challenge": "This is not credible. Discard the Undervalued verdict as it stands."}]}
    m = _model(blend({"dcf": 431.86, "comps": 600.0, "history": 700.0}, price=300.0), 431.86)
    assert m.verdict.fallback is None
    reason = apply_headline_review(m, review)
    assert reason and "Fair value blend" in reason
    assert m.verdict.fallback == "review_desk" and m.verdict.fair_value == pytest.approx(431.86)
    assert m.verdict.confidence == "Low" and m.verdict.headline_note.startswith("The review desk")
    assert "scenario-weighted DCF" in m.trace["fair_value"].formula


def test_PLTR_review_headline_check_false_also_fires():
    assert headline_challenge({"headline_check": {"credible": False, "target": "blend",
                                                  "reason": "the 66.4% gap has little meaning"}})
    assert headline_challenge({"headline_check": {"credible": True, "target": "none", "reason": ""},
                               "challenges": [{"assumption": "WACC", "severity": "high", "challenge": "x"}]}) is None
    assert headline_challenge({"challenges": [{"assumption": "Margin path", "severity": "medium",
                                               "challenge": "x"}]}) is None
    assert headline_challenge({"challenges": [{"assumption": "Terminal growth margin path", "severity": "high",
                                               "challenge": "Margin held at a peak. It fades too late."}]})


# --- Priority 1.2: the rating follows the evidence -----------------------------------------------------------------------
def test_MU_strong_buy_is_capped_when_no_monte_carlo_run_beats_the_price():
    rating, notes = gate_by_evidence("Strong Buy", fair_value=2338.54, price=900.0, dcf_bull=1500.0, prob_above=0.0)
    assert rating == "Hold" and "0% of Monte Carlo" in notes[0]


def test_NVDA_strong_buy_is_capped_at_2_percent_of_runs_above_the_price():
    rating, _ = gate_by_evidence("Strong Buy", fair_value=190.0, price=190.0, dcf_bull=300.0, prob_above=0.02)
    assert rating == "Hold"


def test_a_buy_needs_the_price_below_the_bull_case():
    rating, notes = gate_by_evidence("Buy", fair_value=190.0, price=200.0, dcf_bull=150.0, prob_above=0.5)
    assert rating == "Hold" and "bull-case DCF" in notes[0]
    assert gate_by_evidence("Buy", fair_value=120.0, price=100.0, dcf_bull=150.0, prob_above=0.5)[0] == "Buy"


def test_SHOP_and_AMD_hold_with_fair_value_70_percent_below_the_price_becomes_sell():
    rating, notes = gate_by_evidence("Hold", fair_value=30.0, price=100.0, dcf_bull=60.0, prob_above=0.1)
    assert rating == "Sell" and "70% below" in notes[0]
    assert gate_by_evidence("Hold", fair_value=80.0, price=100.0, dcf_bull=120.0, prob_above=0.4)[0] == "Hold"


def test_a_buy_with_fair_value_far_below_the_price_ends_at_sell():
    assert gate_by_evidence("Buy", fair_value=30.0, price=100.0, dcf_bull=60.0, prob_above=0.1)[0] == "Sell"


# --- Priority 1.3: one DCF per report ---------------------------------------------------------------------------------------
AMD_PAYLOAD = {"price": 250.0, "dcf": {"value_per_share": 381.17,
                                       "figures": {"base_case": 381.17, "bear": 210.0, "base": 381.17, "bull": 600.0,
                                                   "probability_weighted": 392.0},
                                       "scenarios": {"Bear": {"value": 210.0}, "Bull": {"value": 600.0}}},
               "verdict": {"fair_value": 392.0, "components": {"dcf": 392.0}}}


def test_AMD_a_text_that_quotes_a_different_dcf_is_dropped():
    data = {"bear_case": {"thesis": "The DCF base value is $44.37 and even the bull scenario is $69.77. "
                                    "Margins look stretched.",
                          "points": ["The DCF base value is $381.17 per share.", "Peers trade lower."]}}
    out, log = drop_wrong_dcf(data, AMD_PAYLOAD, "Review desk")
    assert out["bear_case"]["thesis"] == "Margins look stretched."
    assert out["bear_case"]["points"] == ["The DCF base value is $381.17 per share.", "Peers trade lower."]
    assert len(log) == 1 and "44.37" in log[0]


def test_dcf_guard_ignores_enterprise_values_and_banks():
    data = {"x": "The DCF gives an enterprise value of $12.4bn against a price of $250.00."}
    assert drop_wrong_dcf(data, AMD_PAYLOAD, "MD")[0] == data
    assert drop_wrong_dcf({"x": "The DCF is $1.00."}, {"price": 5.0}, "MD")[0] == {"x": "The DCF is $1.00."}


# --- Priority 2: stage and cycle -------------------------------------------------------------------------------------
def test_SNDK_memory_chipmaker_is_cyclical_not_pre_profit_despite_175_percent_growth():
    h = hist([4000.0, 3600.0, 9900.0], [-900.0, -1500.0, 7200.0], fcf=[-300.0, -800.0, 5000.0])
    c = classify(h, "3572", current_margin=7200.0 / 9900.0)
    assert c.stage == CYCLICAL, c.stage_reason


def test_SHOP_profitable_fast_grower_is_high_growth_not_pre_profit():
    h = hist([5600.0, 7100.0, 8900.0, 11500.0], [100.0, 700.0, 1200.0, 1680.0], fcf=[200.0, 900.0, 1700.0, 2700.0])
    c = classify(h, "7372", current_margin=1680.0 / 11500.0)
    assert c.stage == HIGH_GROWTH, c.stage_reason


def test_a_genuine_pre_profit_company_is_still_early():
    h = hist([100.0, 200.0, 350.0, 600.0], [-80.0, -90.0, -70.0, -40.0], fcf=[-60.0, -70.0, -50.0, -20.0])
    assert classify(h, "7372", current_margin=-40.0 / 600.0).stage == EARLY


def test_MU_cycle_target_ignores_a_trough_year():
    """MU's -37% trough must not drag the mid-cycle target down: it is half way between the median and the 90th percentile."""
    margins = [-0.37, 0.15, 0.20, 0.18, 0.25, 0.30, 0.28, 0.20, 0.22, 0.50]
    h = hist([1000.0] * 10, [m * 1000 for m in margins])
    cyc = cycle_position(h, 0.746)
    assert cyc["cycle_target_margin"] > cyc["mid_cycle_margin"]
    assert cyc["cycle_target_margin"] == pytest.approx((cyc["median_margin"] + cyc["p90_margin"]) / 2)


def _plan(stage, **kw):
    h = historicals_for("KO")
    args = dict(valuation_date=date(2026, 10, 14), current_margin=r(0.30), consensus=[], industry_margin=r(0.15),
                industry_growth=r(0.06), industry_sales_to_capital=r(1.5), effective_tax=r(0.20), marginal_tax=r(0.25),
                risk_free=r(0.045), wacc=0.09, roic=r(0.2), mid_cycle_margin=0.2, five_year_avg_margin=0.2)
    args.update(kw)
    return build_plan(h, stage, **args)


def test_MU_NVDA_cyclical_margin_fades_in_a_straight_line_not_a_cliff():
    p = _plan("cyclical", current_margin=r(0.746), cycle_target_margin=0.28)
    m = p.path("operating_margin")
    steps = [a - b for a, b in zip(m[1:], m[2:])]
    assert m[0] == pytest.approx(0.746) and m[-1] == pytest.approx(0.28)
    assert all(s > 0 for s in steps) and max(steps) - min(steps) < 1e-9
    assert max(steps) < 0.12  # MU's old path dropped 50 points in one year
    assert len(m) >= 7


def test_PLTR_SNDK_MU_effective_tax_phases_up_to_the_marginal_rate_by_year_5():
    p = _plan("mature_growth", effective_tax=r(0.014))
    t = p.path("tax_rate")
    first = len(p.skipped)
    assert t[first] == pytest.approx(0.014)
    assert t[first + 4] == pytest.approx(0.25) and all(a <= b + 1e-12 for a, b in zip(t, t[1:]))


def test_MU_terminal_roic_of_a_cyclical_is_wacc_plus_4_points():
    p = _plan("cyclical", roic=r(0.254), wacc=0.09)
    assert p.terminal_roic.value == pytest.approx(0.13)
    assert _plan("mature_growth", roic=r(0.254), wacc=0.09).terminal_roic.value > 0.15  # other stages unchanged


# --- Priority 3: forecast inputs ---------------------------------------------------------------------------------------
def test_PLTR_AMD_INTC_growth_is_capped_at_the_best_year_and_never_re_accelerates():
    # PLTR: consensus 46.8% then back up to 121%, against a best year of 56%
    assert fade_growth([0.80, 0.468, 0.90, 1.21, 0.60], cap=0.56, floor_rate=0.06) == \
        pytest.approx([0.56, 0.468, 0.468, 0.468, 0.468])
    # below the industry rate nothing is forced upwards
    assert fade_growth([0.04, 0.03, 0.05], cap=0.5, floor_rate=0.06) == pytest.approx([0.04, 0.03, 0.05])


def test_AMD_raw_consensus_is_kept_for_the_bull_case_only():
    from engine.forecast import ConsensusYear
    h = historicals_for("UBER")
    fy25 = h.v("revenue", "FY2025")
    cons = [ConsensusYear(date(2026 + k, 12, 31), fy25 * (1.6 ** (k + 1)), 0, 0, None, 12, "test") for k in range(4)]
    p = _plan("high_growth", consensus=cons)
    assert p.raw_growth_path is not None and max(p.raw_growth_path) > max(p.path("revenue_growth")) + 0.05
    g = p.path("revenue_growth")
    assert all(a >= b - 1e-12 for a, b in zip(g, g[1:]))  # non-increasing


def test_INTC_a_dcf_with_terminal_value_above_ev_is_a_model_fit_failure():
    ys = tuple(YearDrivers(f"FY{2026 + k}E", 0.20, 0.10, 0.25, sales_to_capital=0.3) for k in range(5))
    d = run_dcf(DCFInputs("FY2025", 1000.0, ys, 0.09, 0.03, terminal_roic=0.12, bridge=(("debt", -100.0),), shares=10.0))
    assert d.tv_share_of_ev > 1.0 or d.sum_pv_fcf < 0
    assert fit_failure(d, 0.10) is not None
    ok = run_dcf(DCFInputs("FY2025", 1000.0, tuple(YearDrivers(f"FY{2026 + k}E", 0.05, 0.2, 0.25, sales_to_capital=2.0)
                                                   for k in range(5)), 0.09, 0.03, terminal_roic=0.15))
    assert fit_failure(ok, 0.2) is None


def test_the_floored_sales_to_capital_is_re_run_for_a_company_that_fails_the_fit_check():
    import copy
    from engine.valuation import value_company
    from tests.engine_fixtures import engine_inputs
    i = copy.deepcopy(engine_inputs("KO"))
    i.overrides = {}
    assert value_company(i).model_fit is None  # a healthy company is untouched
    # a low company sales-to-capital produces a bad first DCF, so it is re-run at the industry figure
    import engine.forecast as f
    orig = f._sales_to_capital
    f._sales_to_capital = lambda h: Value(0.31, None, "x", "test", "test")
    try:
        v = value_company(i)
    finally:
        f._sales_to_capital = orig
    if v.model_fit is not None:
        assert v.model_fit["industry_sales_to_capital"] > v.model_fit["company_sales_to_capital"]
        assert any(fl.code in ("model_fit_rerun", "model_fit_failed") for fl in v.flags)


# --- Priority 2.6: comps on mid-cycle earnings ---------------------------------------------------------------------------
def test_MU_SNDK_comps_use_mid_cycle_earnings_not_peak_earnings():
    me = CompanyMetrics("MU", "Micron", "3674", 120_000.0, 100.0, 40_000.0, 28_000.0, 18_000.0, 13_000.0, 6.0, 15_000.0,
                        20_000.0, operating_income=24_000.0)  # a 60% operating margin
    got = mid_cycle_metrics(me, 0.28, 0.21)
    assert got is not None
    norm, note = got
    assert norm.operating_income == pytest.approx(0.28 * 40_000.0)
    assert norm.net_income < me.net_income and norm.ebitda < me.ebitda and "mid-cycle" in note
    assert mid_cycle_metrics(me, 0.70, 0.21) is None  # not above the target: nothing to normalise
    peers = [CompanyMetrics(f"P{i}", f"P{i}", "3674", 100_000.0, 50.0, 30_000.0, 9_000.0, 5_000.0, 4_000.0, 4.0, 5_000.0,
                            8_000.0, operating_income=7_000.0) for i in range(5)]
    peak = run_comps(me, peers, ["test"], 1000.0, 5_000.0)
    mid = run_comps(me, peers, ["test"], 1000.0, 5_000.0, normalised=norm, normalised_note=note)
    assert mid.multiples["pe_trailing"].implied_price < peak.multiples["pe_trailing"].implied_price
    assert mid.normalised_note and not peak.normalised_note
    assert mid.multiples["pe_trailing"].company_value == peak.multiples["pe_trailing"].company_value  # actual shown


# --- Priority 4: peers -------------------------------------------------------------------------------------------------
def test_peer_blocklist_and_named_groups():
    for t in ("MSTR", "GE", "GEV"):
        assert t in PEER_BLOCKLIST
        assert not is_true_peer(t, "3674", "MU", "3674")
    assert {"WDC", "STX", "SNDK"} <= set(peer_group("MU")[1]) and {"AMD", "AVGO"} <= set(peer_group("NVDA")[1])


def test_PLTR_MU_SNDK_peers_need_a_3_digit_sic_match_or_a_named_peer():
    assert not is_true_peer("DELL", "3571", "SNDK", "3572")                  # a named industry needs the same 4-digit SIC
    assert not is_true_peer("HPE", "3571", "SNDK", "3572") and not is_true_peer("FTNT", "3577", "SNDK", "3572")
    assert is_true_peer("WDC", "9999", "SNDK", "3572") and is_true_peer("STX", "9999", "SNDK", "3572")  # named
    assert is_true_peer("NTAP", "3572", "SNDK", "3572")                      # same 4-digit SIC
    assert is_true_peer("ADBE", "7372", "PLTR", "7372") and not is_true_peer("MSFT", "3571", "PLTR", "7372")
    assert not is_true_peer("GE", "3510", "MU", "3674")


def test_SHOP_fewer_than_5_true_peers_gives_comps_no_weight():
    """modelling: comps_usable needs MIN_PEERS true peers; without them the blend has no comps component."""
    v = blend({"dcf": 100.0, "comps": None, "history": 110.0}, price=100.0)
    assert "comps" not in v.weights_used and "not available" in "; ".join(v.notes)


# --- Priority 5: data quality -------------------------------------------------------------------------------------------
def test_SHOP_SNDK_partial_report_banner_when_the_provider_refused_requests():
    notes = ["FMP: rate limited (HTTP 429); not retried for 60s"]
    out = top_notes([], notes, ["analyst consensus", "price history"])
    assert out and out[0].startswith("Partial report") and "analyst consensus and price history are" in out[0]
    assert top_notes([], [], ["analyst consensus"]) == []  # no refusal: not a partial run, just a missing input


def test_AMD_a_red_flag_is_printed_at_the_top():
    red = Flag(RED, "cash_flow_tie", "Cash flow does not tie to the change in cash", "x", "FY2021", {})
    out = top_notes([red], [], [])
    assert out and "Cash flow does not tie" in out[0] and "FY2021" in out[0]


def test_red_flags_cost_three_points_of_confidence():
    v = blend({"dcf": 100.0, "comps": 100.0, "history": 100.0}, price=100.0)
    level, _ = confidence(v, estimate_dispersion=0.05, red_flags=1, amber_flags=0, tv_share=0.5, completeness=1.0)
    assert level == "Low"


def test_INTC_share_counts_that_differ_are_shown_side_by_side_and_the_filing_is_used():
    f = checks.share_count_gap(4530.0, "10-Q cover page, 2025-10-24", 4856.0, "FMP")
    assert f and "4,530.0m" in f[0].message and "4,856.0m" in f[0].message and "filing figure is the one used" in f[0].message
    assert checks.share_count_gap(4530.0, "x", 4600.0, "FMP") == []


def test_INTC_diluted_count_far_above_the_cover_page_is_flagged():
    f = checks.dilution_gap(4530.0, 5326.0, "basic + RSUs")
    assert f and "17.6%" in f[0].message
    assert checks.dilution_gap(4530.0, 4700.0) == []


def test_PLTR_MU_INTC_a_balance_sheet_item_missing_at_the_bridge_date_counts_as_zero():
    import copy
    from engine.valuation import value_company
    from tests.engine_fixtures import engine_inputs
    i = copy.deepcopy(engine_inputs("KO"))
    ltm = i.historicals.ltm.label
    fy = i.historicals.fy_labels[-2]
    i.historicals.lines["preferred_equity"] = {fy: Value(500.0, "USD", MILLIONS, fy, "test")}  # an old FY2021-style figure
    v = value_company(i)
    assert not any(n == "Preferred equity" for n, _ in v.bridge)
    flag = next(f for f in v.flags if f.code == "bridge_mixed_periods")
    assert "preferred equity (500m at" in flag.message and "treated as zero" in flag.message
    assert ltm in flag.message


# --- Priority 6: freshness -----------------------------------------------------------------------------------------------
class _Stub:
    def __init__(self, **methods):
        self.__dict__.update(methods)


def _c(payload):
    return Cached(payload, datetime(2026, 11, 9, tzinfo=timezone.utc), False, "k", "price")


def test_NVDA_a_stale_first_quote_is_replaced_by_a_fresher_one(monkeypatch):
    import datasources.market as market
    monkeypatch.setattr(market, "STALE_HOURS", 6)
    old = int(datetime(2026, 11, 6, 21, 0, tzinfo=timezone.utc).timestamp())
    new = int(datetime.now(timezone.utc).timestamp())
    md = MarketData(_Stub(call=lambda n, s, **k: _c([{"price": 180.0, "timestamp": old}])),
                    _Stub(quote=lambda s: _c([{"tngoLast": 183.5, "timestamp": datetime.now(timezone.utc).isoformat()}])),
                    _Stub(call=lambda n, s, **k: _c({"c": 181.0, "t": new - 3600})))
    r = md.quote("NVDA")
    assert r.source == "Tiingo" and r.data["price"] == 183.5
    assert any("looked stale" in n for n in r.notes)


def test_NVDA_next_earnings_date_comes_from_the_calendar():
    rows = [{"date": "2026-08-27", "epsActual": 1.05, "epsEstimated": 1.0},
            {"date": "2026-11-17", "epsActual": None, "epsEstimated": 1.31},
            {"date": "2027-02-25", "epsActual": None, "epsEstimated": 1.5}]
    md = MarketData(_Stub(call=lambda n, s, **k: _c(rows)), _Stub(), _Stub(call=lambda *a, **k: _c({})))
    r = md.next_earnings("NVDA", today=date(2026, 11, 9))
    assert r.data == {"date": "2026-11-17", "eps_estimate": 1.31}
    none = MarketData(_Stub(call=lambda n, s, **k: _c([])), _Stub(), _Stub(call=lambda *a, **k: _c({"earningsCalendar": []})))
    assert not none.next_earnings("NVDA", today=date(2026, 11, 9)).available


def test_NVDA_the_news_desk_is_told_the_price_date():
    from desks.news import price_date
    cd = SimpleNamespace(market=SimpleNamespace(price=SimpleNamespace(period="2026-11-06T21:00:00+00:00")))
    assert price_date(cd) == "2026-11-06"
    assert price_date(SimpleNamespace(market=SimpleNamespace(price=SimpleNamespace(period="latest")))) is None


def test_SNDK_reverse_dcf_solves_for_the_implied_cagr_and_margin_when_the_walk_cannot_close_the_gap():
    from tests.test_engine import simple
    inp = simple(years=5)
    base = run_dcf(inp).value_per_share
    steps = price_walk(inp, base * 30, None, None, None, risk_free=0.045)
    last = steps[-1]
    assert last["label"] == "Not explained" and last["implied"] is not None
    assert last["implied"]["implied_cagr"] > last["implied"]["base_cagr"]
    assert "revenue CAGR of" in last["detail"]


def test_fall_back_without_a_dcf_keeps_the_blend_but_says_so():
    v = blend({"dcf": None, "comps": 100.0, "history": 100.0}, price=90.0)
    out = fall_back_to_dcf(v, None, "The review desk judged the blended fair value not credible.", "review_desk")
    assert out.fair_value == v.fair_value and out.confidence == "Low" and "do not rely" in out.headline_note
