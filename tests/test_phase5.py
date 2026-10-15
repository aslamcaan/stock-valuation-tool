"""Phase 5: comps, benchmarking, historical multiples, estimate revisions, verdict rules, confidence, football field."""
from datetime import date

import pytest

from core.store import Store
from engine.comps import CompanyMetrics, benchmark, implied_from_multiple, run_comps, select_peers
from engine.history_multiples import YearPoint, history_multiples, split_adjusted_closes
from engine.verdict import FAIR, OVERVALUED, UNDERVALUED, blend, confidence, football_field


def cm(t, mcap, sic="2080", rev=100.0, ebitda=20.0, fcf=10.0, ni=8.0, debt=10.0, cash=5.0, price=10.0, eps=None, **b):
    return CompanyMetrics(t, t, sic, mcap, price, rev, ebitda, fcf, ni, eps, debt, cash, benchmarks=b)


# --- peer selection -----------------------------------------------------------------------------------------
def test_peer_filter_same_sic_and_size():
    me = cm("ME", 1000)
    cands = [cm(f"P{i}", 1000 * (0.5 + i * 0.3)) for i in range(5)] + [cm("BIG", 5000), cm("OTHER", 1000, sic="7372")]
    peers, steps = select_peers(me, cands)
    assert {p.ticker for p in peers} == {"P0", "P1", "P2", "P3", "P4"}
    assert steps == ["same SIC, 0.25x-4x market cap: 5 peers"]


def test_peer_filter_widens_and_says_so():
    me = cm("ME", 1000)
    cands = [cm("A", 900), cm("B", 1100, sic="2086"), cm("C", 800, sic="2099"), cm("D", 1200, sic="7372"),
             cm("E", 3000, sic="5812")]
    peers, steps = select_peers(me, cands)
    assert len(peers) == 5 and len(steps) == 4 and steps[-1].startswith("any SIC among the candidates")


# --- multiples and implied prices --------------------------------------------------------------------------------
def test_ev_multiple_implied_price_uses_bridge_and_shares():
    me = cm("ME", 1000)
    # EV/EBITDA 10x on EBITDA 20 = EV 200; bridge -5 (cash 5 - debt 10); 10 shares -> 19.5
    assert implied_from_multiple("ev_ebitda", 10.0, me, shares=10, bridge=-5, adr_ratio=1) == pytest.approx(19.5)
    assert implied_from_multiple("pe_trailing", 20.0, me, shares=10, bridge=-5, adr_ratio=1) == pytest.approx(16.0)
    assert implied_from_multiple("ev_ebitda", 10.0, cm("X", 1, ebitda=-5), shares=10, bridge=0, adr_ratio=1) is None


def test_run_comps_medians_and_negative_multiples_excluded():
    me = cm("ME", 1000)
    peers = [cm("A", 1000, ebitda=50), cm("B", 1000, ebitda=100), cm("C", 1000, ebitda=200), cm("D", 1000, ebitda=-10)]
    r = run_comps(me, peers, ["test"], shares=100, bridge=-5)
    ev = r.multiples["ev_ebitda"]
    assert set(ev.peer_values) == {"A", "B", "C"}  # D has negative EBITDA
    assert ev.median == pytest.approx(1005 / 100)
    assert r.implied_price is not None


def test_benchmark_percentiles():
    me = cm("ME", 1000, operating_margin=0.30, net_debt_to_ebitda=1.0)
    peers = [cm(t, 1000, operating_margin=m, net_debt_to_ebitda=l) for t, m, l in
             (("A", 0.1, 2.0), ("B", 0.2, 3.0), ("C", 0.4, 0.5), ("D", 0.25, 4.0))]
    b = benchmark(me, peers)
    assert b["operating_margin"]["percentile"] == pytest.approx(0.75)
    assert b["net_debt_to_ebitda"]["percentile"] == pytest.approx(0.75)  # lower leverage is better
    assert b["operating_margin"]["peer_median"] == pytest.approx(0.225)


# --- historical multiples ---------------------------------------------------------------------------------------------
def test_split_adjustment():
    rows = [{"date": "2020-08-28", "close": 400.0, "splitFactor": 1.0},
            {"date": "2020-08-31", "close": 125.0, "splitFactor": 4.0},
            {"date": "2020-09-01", "close": 130.0, "splitFactor": 1.0}]
    c = split_adjusted_closes(rows)
    assert c["2020-08-28"] == pytest.approx(100.0) and c["2020-08-31"] == 125.0 and c["2020-09-01"] == 130.0


def test_history_range_and_implied_price():
    pts = [YearPoint(f"FY{y}", date(y, 12, 31), 10.0 * k, 10, 10, 5, 0, 100, 20, 10, 8)
           for y, k in zip(range(2021, 2026), (1.0, 1.2, 0.8, 1.1, 0.9))]
    res = history_multiples(pts, {"ev_ebitda": 7.0}, {"ebitda": 20.0}, shares=10, bridge=-5)
    h = res["ev_ebitda"]
    evs = sorted((10 * k * 10 + 5) / 20 for k in (1.0, 1.2, 0.8, 1.1, 0.9))
    assert (h.low, h.median, h.high) == pytest.approx((evs[0], evs[2], evs[-1]))
    assert h.implied_price == pytest.approx((h.median * 20 - 5) / 10)
    assert h.percentile == pytest.approx(1.0)  # 7.0x is above every year in the range (max 6.25x)


# --- estimate revisions -------------------------------------------------------------------------------------------------
def test_revisions_from_own_snapshots(tmp_path):
    s = Store(tmp_path / "t.sqlite")
    s.save_snapshot("KO", [{"fiscal_year_end": "2026-12-31", "revenue_avg": 100.0, "eps_avg": 2.0, "analysts": 10}],
                    date(2026, 7, 15))
    out = s.revisions("KO", date(2026, 10, 14), [{"fiscal_year_end": "2026-12-31", "revenue_avg": 105.0, "eps_avg": 1.9}])
    assert out[90]["available"] and out[90]["changes"]["2026-12-31"]["revenue"] == pytest.approx(0.05)
    assert out[90]["changes"]["2026-12-31"]["eps"] == pytest.approx(-0.05)
    assert not out[30]["available"] and "30 days" in out[30]["reason"]


# --- verdict rules ----------------------------------------------------------------------------------------------------
def test_verdict_bands_and_weights():
    v = blend({"dcf": 100, "comps": 100, "history": 100}, price=80)
    assert v.fair_value == 100 and v.verdict == UNDERVALUED  # 80 is 20% below 100
    assert blend({"dcf": 100, "comps": 100, "history": 100}, price=90).verdict == FAIR
    assert blend({"dcf": 100, "comps": 100, "history": 100}, price=120).verdict == OVERVALUED
    v = blend({"dcf": 100, "comps": 200, "history": 300}, price=150)
    assert v.fair_value == pytest.approx(0.5 * 100 + 0.3 * 200 + 0.2 * 300)


def test_missing_method_rescales_and_sotp_replaces_dcf():
    v = blend({"dcf": 100, "comps": None, "history": 200}, price=100)
    assert v.weights_used == pytest.approx({"dcf": 0.5 / 0.7, "history": 0.2 / 0.7})
    assert "rescaled" in v.notes[0]
    v = blend({"dcf": 100, "comps": 100, "history": 100}, price=100, sotp=160)
    assert v.fair_value == pytest.approx(0.5 * 160 + 0.5 * 100)


def test_confidence_levels():
    good = blend({"dcf": 100, "comps": 100, "history": 100}, price=100)
    assert confidence(good, estimate_dispersion=0.05, red_flags=0, amber_flags=1, tv_share=0.6, completeness=1)[0] == "High"
    lvl, why = confidence(good, estimate_dispersion=None, red_flags=1, amber_flags=5, tv_share=0.9, completeness=0.5)
    assert lvl == "Low" and any("terminal value" in r for r in why)
    lvl, _ = confidence(good, estimate_dispersion=0.05, red_flags=0, amber_flags=0, tv_share=0.6, completeness=1,
                        peers_meet_brief_filter=False)
    assert lvl == "Medium"


def test_football_field_bars():
    bars = football_field(dcf_bear=80, dcf_base=100, dcf_bull=130, comps={}, history={},
                          analyst_targets={"low": 90, "high": 140, "median": 110}, week52=(70, 120))
    assert [b.method for b in bars] == ["DCF (bear-bull)", "Analyst price targets", "52-week trading range"]
    assert bars[0].low == 80 and bars[0].high == 130
