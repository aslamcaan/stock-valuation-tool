"""Data checks: thresholds from CLAUDE.md ACCURACY RULES."""
from datetime import date

from data_desk import checks
from engine.flags import AMBER, HARD_STOP, RED
from engine.model import Historicals, Period
from engine.values import Value


def hist(**lines_by_period) -> Historicals:
    """lines_by_period: line -> {period: value}."""
    labels = sorted({p for d in lines_by_period.values() for p in d})
    periods = [Period(lab, date(int(lab[2:]), 12, 31), None, "FY") for lab in labels]
    lines = {k: {p: Value(v, "USD", "m", p, "test") for p, v in d.items()} for k, d in lines_by_period.items()}
    return Historicals("USD", "us-gaap", periods, lines)


def test_balance_sheet_hard_stop_only_in_valuation_period():
    h = hist(total_assets={"FY2024": 100, "FY2025": 100}, total_liabilities={"FY2024": 60, "FY2025": 60},
             total_equity={"FY2024": 39, "FY2025": 39.6})
    flags = checks.balance_sheet(h, ["FY2025"])
    assert [(f.period, f.level) for f in flags] == [("FY2024", RED)]  # FY2025 off by 0.4% -> fine
    h.lines["total_equity"]["FY2025"] = Value(38, "USD", "m", "FY2025", "test")
    assert any(f.level == HARD_STOP and f.period == "FY2025" for f in checks.balance_sheet(h, ["FY2025"]))


def test_temporary_equity_counts_towards_balance():
    h = hist(total_assets={"FY2025": 100}, total_liabilities={"FY2025": 60}, total_equity={"FY2025": 30},
             temporary_equity={"FY2025": 10})
    assert checks.balance_sheet(h, ["FY2025"]) == []


def test_market_cap_hard_stop_and_approximate():
    assert checks.market_cap(1000, 1029, "FMP", "") == []
    assert checks.market_cap(1000, 1040, "FMP", "")[0].level == HARD_STOP
    assert checks.market_cap(1000, 1040, "FMP", "", point_in_time_shares=False)[0].level == AMBER
    assert checks.market_cap(None, 1040, "FMP", "no price")[0].code == "mcap_unchecked"
    assert checks.market_cap(1000, 1040, "Finnhub", "")[0].code == "mcap_mismatch_secondary"


def test_cash_flow_tie():
    ok = hist(cfo={"FY2025": 100}, cfi={"FY2025": -60}, cff={"FY2025": -30}, fx_effect_on_cash={"FY2025": -2},
              change_in_cash={"FY2025": 8})
    assert checks.cash_flow_tie(ok) == []
    bad = hist(cfo={"FY2025": 100}, cfi={"FY2025": -60}, cff={"FY2025": -30}, change_in_cash={"FY2025": 20})
    f = checks.cash_flow_tie(bad)
    assert f and f[0].level == RED and f[0].numbers["reported_change"] == 20


def test_gross_profit_sum_red_flag():
    h = hist(revenue={"FY2025": 100}, cost_of_revenue={"FY2025": 60}, gross_profit={"FY2025": 45})
    assert checks.statement_sums(h)[0].code == "is_gross_profit_sum"


def test_cross_source_amber_over_two_percent():
    f = checks.cross_source({"revenue": 100, "cash": 50}, {"revenue": 101.9, "cash": 52}, "FMP", "FY2025")
    assert [x.code for x in f] == ["xsource_cash"] and f[0].level == AMBER
    assert f[0].numbers["edgar"] == 50 and f[0].numbers["FMP"] == 52


def test_stale_filing():
    assert checks.filing_age("2026-06-01", "10-Q", date(2026, 9, 28)) == []
    assert checks.filing_age("2026-03-06", "20-F", date(2026, 10, 14))[0].numbers["age_days"] == 222


def test_net_income_rule_needs_both_conditions():
    # gap > 50% of OI but < 5% of revenue -> no flag (Uber FY2023 shape)
    h = hist(net_income_attributable={"FY2025": 1887}, operating_income={"FY2025": 1110}, revenue={"FY2025": 37281})
    assert checks.net_income_vs_operating(h) == []
    h = hist(net_income_attributable={"FY2025": 9856}, operating_income={"FY2025": 2799}, revenue={"FY2025": 43978})
    assert checks.net_income_vs_operating(h)[0].numbers == {"net_income": 9856, "operating_income": 2799,
                                                            "revenue": 43978}


def test_negative_fcf_flag():
    assert checks.negative_fcf(hist(fcf={"FY2025": -18}))[0].code == "negative_fcf"
    assert checks.negative_fcf(hist(fcf={"FY2025": 5})) == []


def test_consensus_and_revisions_read_the_nearest_year_first(tmp_path):
    """FMP lists the furthest fiscal year first; the engine and the rubric must use the nearest unended year."""
    from datetime import date
    from types import SimpleNamespace
    from core.store import Store
    from data_desk.valuation_inputs import consensus_rows
    rows = [{"date": f"{y}-12-31", "revenueAvg": y * 1e6, "numAnalystsRevenue": 10} for y in (2030, 2028, 2026, 2027)]
    svc = SimpleNamespace(market=SimpleNamespace(analyst_estimates=lambda t: SimpleNamespace(
        available=True, data=rows, notes=[], fetched_at="t")))
    out, _ = consensus_rows(svc, "X", "USD")
    assert [c.fiscal_year_end.year for c in out] == [2026, 2027, 2028, 2030]
    store = Store(tmp_path / "s.sqlite")
    snap = [{"fiscal_year_end": f"{y}-12-31", "revenue_avg": 100.0, "eps_avg": 1.0} for y in (2030, 2026, 2025)]
    store.save_snapshot("X", snap, date(2026, 6, 1))
    now = [{"fiscal_year_end": f"{y}-12-31", "revenue_avg": 100.0 + y - 2025, "eps_avg": 1.0} for y in (2030, 2026, 2025)]
    rev = store.revisions("X", date(2026, 9, 5), now)[90]
    assert list(rev["changes"]) == ["2026-12-31", "2030-12-31"]  # FY2025 has ended: not a revision signal


def test_volume_kpi_from_the_filing_drives_the_divergence_flag():
    """UBER: Gross Bookings 162,773 -> 193,454 (+18.8%) vs revenue 43,978 -> 52,017 (+18.3%): no flag;
    a KPI growing 30% would be 11.7 points apart: flag."""
    from types import SimpleNamespace
    from desks.modelling import kpi_flags
    h = hist(revenue={"FY2024": 43978, "FY2025": 52017})
    cd = SimpleNamespace(historicals=h)
    ok = {"name": "Gross Bookings", "values": [{"fiscal_year": "2024", "value_millions": 162773},
                                               {"fiscal_year": "fiscal 2025", "value_millions": 193454}]}
    assert kpi_flags(cd, ok) == []
    off = {"name": "Gross Bookings", "values": [{"fiscal_year": "FY2024", "value_millions": 100},
                                                {"fiscal_year": "FY2025", "value_millions": 130}]}
    assert [f.code for f in kpi_flags(cd, off)] == ["kpi_divergence"]


def test_volume_kpi_values_must_be_in_the_filing():
    from desks.research import verify
    src = "Gross Bookings were $193.5 billion in 2025 and $162,773 million in 2024."
    data = {"volume_kpi": {"name": "Gross Bookings", "quote": "Gross Bookings were $193.5 billion in 2025",
                           "values": [{"fiscal_year": "2025", "value_millions": 193500},
                                      {"fiscal_year": "2024", "value_millions": 162773},
                                      {"fiscal_year": "2023", "value_millions": 137865}]}}
    out, dropped = verify(data, src)
    assert [x["fiscal_year"] for x in out["volume_kpi"]["values"]] == ["2025", "2024"] and dropped


def test_cash_flow_ties_before_reclassification_to_held_for_sale():
    """UNH FY2025: the sections sum to the change in cash including disposal groups, not the reported total."""
    h = hist(cfo={"FY2025": 19697}, cfi={"FY2025": -8685}, cff={"FY2025": -11644}, fx_effect_on_cash={"FY2025": 40},
             change_in_cash={"FY2025": -947}, change_in_cash_incl_disposal={"FY2025": -592})
    assert checks.cash_flow_tie(h) == []
