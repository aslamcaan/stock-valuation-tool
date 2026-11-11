"""Feature tests for the November additions: expectations box, risk and reward line, compare table, sizing, tracker."""
import pytest

from engine.expectations import expectations, risk_reward
from tests.feature_fixtures import fake_report


def test_expectations_solve_the_price_and_compare_with_the_best_year():
    rep = fake_report("KO", price_factor=2.0)            # a price twice our base DCF needs more than our base case
    e = expectations(rep)
    assert e["implied_cagr"] > e["base_cagr"] and e["implied_terminal_margin"] > e["base_terminal_margin"]
    assert e["best_year_growth"] is not None and e["best_year"].startswith("FY")
    assert "needs" in e["lines"][0] and "Best year on record" in e["lines"][0] and "$" in e["lines"][0]
    assert any("terminal operating margin" in x for x in e["lines"])
    assert e["stretch"] is True                          # KO cannot grow as fast as 2x our DCF needs


def test_a_price_at_our_base_dcf_needs_our_base_case():
    rep = fake_report("KO", price_factor=1.0)
    e = expectations(rep)
    assert e["implied_cagr"] == pytest.approx(e["base_cagr"], abs=2e-3)
    assert e["implied_terminal_margin"] == pytest.approx(e["base_terminal_margin"], abs=2e-3)


def test_expectations_say_so_when_no_history_or_no_solution(monkeypatch):
    rep = fake_report("KO", price_factor=1.5)
    rep.company.analysis = None                          # no growth history at all
    e = expectations(rep)
    assert "best year on record is not available" in e["lines"][0].lower()
    import engine.expectations as ex
    monkeypatch.setattr(ex, "implied_assumptions", lambda *a, **k: None)
    assert "No growth rate or margin" in expectations(rep)["lines"][0]


def test_risk_reward_line_has_the_three_cases_monte_carlo_and_expected_return():
    rep = fake_report("KO", price_factor=0.8)
    r = risk_reward(rep)
    v = rep.model.valuation.dcf_figures
    price = rep.model.verdict.price
    assert r["pct"]["base"] == pytest.approx(v["base"] / price - 1)
    assert r["expected_return"] == pytest.approx((0.25 * v["bear"] + 0.5 * v["base"] + 0.25 * v["bull"]) / price - 1)
    assert 0.0 <= r["prob_above_price"] <= 1.0
    assert r["line"].count("·") == 4 and "25/50/25" in r["line"] and "Monte Carlo" in r["line"]


def test_risk_reward_flags_a_dcf_that_failed_its_fit_check():
    rep = fake_report("KO")
    rep.model.valuation.model_fit_failed = True
    assert "unreliable" in risk_reward(rep)["line"]


def test_banks_have_no_expectations_box():
    rep = fake_report("KO")
    rep.model.financial = object()
    assert expectations(rep) is None and risk_reward(rep) is None


# --- compare mode ------------------------------------------------------------------------------------------------
def _reps():
    from types import SimpleNamespace
    out = []
    for factor, tk in ((0.7, "AAA"), (1.0, "BBB"), (1.6, "CCC")):
        rep = fake_report("KO", price_factor=factor)
        rep.ticker = tk
        rep.model.inputs = SimpleNamespace(price=SimpleNamespace(period="2026-11-09T21:00:00+00:00"),
                                           risk_free=rep.model.inputs.risk_free)
        out.append(rep)
    return out


def test_compare_ranks_by_expected_return_and_keeps_missing_figures_empty():
    from engine.compare_table import ranked
    rows = ranked(_reps())
    assert [r["ticker"] for r in rows] == ["AAA", "BBB", "CCC"]     # the lowest price has the highest return
    assert [r["rank"] for r in rows] == [1, 2, 3]
    assert rows[0]["expected_return"] > rows[1]["expected_return"] > rows[2]["expected_return"]
    r = rows[0]
    assert r["price_date"] == "2026-11-09" and r["basis"] == "DCF, 25/50/25"
    assert r["pct_bull"] == pytest.approx(r["bull"] / r["price"] - 1)
    assert r["fwd_pe"] is None and r["pe_median"] is None            # no company metrics or P/E history: left empty


def test_compare_fills_the_pe_columns_from_the_report():
    from types import SimpleNamespace
    from engine.compare_table import row_for
    rep = fake_report("KO", price_factor=1.0)
    rep.model.inputs = SimpleNamespace(price=SimpleNamespace(period="2026-11-09"), risk_free=rep.model.inputs.risk_free)
    rep.model.company_metrics = SimpleNamespace(forward_eps=rep.model.verdict.price / 20)
    rep.model.history = {"pe_trailing": SimpleNamespace(current=30.0, median=24.0, series={"FY1": 1, "FY2": 2})}
    r = row_for(rep)
    assert r["fwd_pe"] == pytest.approx(20.0) and r["pe_vs_median"] == pytest.approx(0.25)


def test_compare_csv_holds_raw_numbers_and_the_pdf_is_one_page():
    import csv
    import io
    import re
    from engine.compare_table import COLUMNS, ranked, to_csv
    from exports.compare_pdf import build_compare_pdf
    rows = ranked(_reps())
    parsed = list(csv.reader(io.StringIO(to_csv(rows))))
    assert parsed[0][0] == "Rank" and len(parsed) == 4 and len(parsed[0]) == len(COLUMNS) + 1
    assert float(parsed[1][parsed[0].index("Expected return")]) == pytest.approx(rows[0]["expected_return"], abs=1e-4)
    pdf = build_compare_pdf(rows)
    assert pdf.startswith(b"%PDF") and len(re.findall(rb"/Type\s*/Page[^s]", pdf)) == 1


def test_compare_without_a_dcf_falls_back_to_the_blended_upside_and_says_so():
    from engine.compare_table import row_for
    rep = fake_report("KO")
    rep.model.financial = type("F", (), {"toolkit": "bank"})()
    rep.model.verdict.fair_value = rep.model.verdict.price * 1.2
    r = row_for(rep)
    assert r["expected_return"] == pytest.approx(0.2) and "no DCF" in r["basis"] and r["bear"] is None


# --- position sizing -------------------------------------------------------------------------------------------------
def test_sizing_converts_at_the_rate_with_the_fee_both_ways():
    from engine.sizing import FX_FEE, size_position
    r = size_position(1000.0, 100.0, 1.25, 20000.0, {"Bear": 70.0, "Base": 130.0}, current_price=100.0)
    units = 1000 * (1 - FX_FEE) * 1.25 / 100
    assert r["units"] == pytest.approx(units)
    flat = r["now"]                                       # price unchanged: only the two fees are lost
    assert flat["pnl_gbp"] == pytest.approx(1000 * ((1 - FX_FEE) ** 2 - 1)) and r["round_trip_fee_drag"] == pytest.approx(
        1 - (1 - FX_FEE) ** 2)
    bear = r["outcomes"]["Bear"]
    assert bear["value_gbp"] == pytest.approx(units * 70.0 / 1.25 * (1 - FX_FEE))
    assert bear["pnl_gbp"] < -290 and bear["pnl_pct"] < -0.29
    assert bear["pnl_pct_of_portfolio"] == pytest.approx(bear["pnl_gbp"] / 20000.0)
    assert r["share_of_portfolio"] == pytest.approx(0.05)
    assert r["outcomes"]["Base"]["pnl_gbp"] > 0


def test_sizing_without_a_portfolio_or_a_target_says_so_and_rejects_nonsense():
    from engine.sizing import size_position
    r = size_position(500.0, 50.0, 1.3, None, {"Bear": None, "Base": 40.0})
    assert r["share_of_portfolio"] is None and r["missing"] == ["Bear"] and "Bear" not in r["outcomes"]
    assert r["outcomes"]["Base"]["pnl_pct_of_portfolio"] is None
    for bad in ((0, 50, 1.3, None), (500, 0, 1.3, None), (500, 50, 0, None), (500, 50, 1.3, 100.0)):
        with pytest.raises(ValueError):
            size_position(*bad, {})


# --- thesis and exit tracker -----------------------------------------------------------------------------------------------
def test_conditions_are_trimmed_deduplicated_and_capped_at_five():
    from engine.thesis import clean_conditions
    assert clean_conditions(["  NVDA data  centre revenue misses guidance ", "", "nvda data centre revenue misses guidance",
                             "Two of META, AMZN, GOOGL guide 2027 capex down"]) == [
        "NVDA data centre revenue misses guidance", "Two of META, AMZN, GOOGL guide 2027 capex down"]
    with pytest.raises(ValueError, match="At most 5"):
        clean_conditions([f"c{i}" for i in range(6)])
    with pytest.raises(ValueError, match="300"):
        clean_conditions(["x" * 301])


def test_a_broken_or_at_risk_status_needs_dated_sourced_evidence_or_is_downgraded():
    from engine.thesis import enforce, overall
    good = {"index": 0, "status": "broken", "evidence": "capex cut 10%", "source": "reuters.com", "date": "2026-11-05",
            "reason": "x"}
    bare = {"index": 1, "status": "at_risk", "evidence": "", "source": "", "date": "", "reason": "feels shaky"}
    odd = {"index": 2, "status": "bearish"}
    out = enforce([good, bare, odd], 4)                    # condition 3 has no result at all
    assert [r["status"] for r in out] == ["broken", "no_evidence", "no_evidence", "no_evidence"]
    assert "Downgraded" in out[1]["reason"] and out[3]["reason"].startswith("The check returned nothing")
    assert overall(out) == "broken" and overall([]) is None
    assert overall(enforce([{"index": 0, "status": "holding", "evidence": "e", "source": "s", "date": "d"}], 1)) == "holding"


def test_holdings_round_trip_through_the_store(tmp_path):
    from core.store import Store
    s = Store(tmp_path / "t.sqlite")
    assert s.holding("NVDA") is None and s.last_checks("NVDA") is None
    s.save_holding("nvda", position_gbp=2000.0, entry_price=140.0, portfolio_gbp=30000.0, thesis="AI capex",
                   conditions=["NVDA data centre revenue misses guidance"])
    h = s.holding("NVDA")
    assert h["position_gbp"] == 2000.0 and h["conditions"] == ["NVDA data centre revenue misses guidance"]
    s.save_holding("NVDA", position_gbp=2500.0, conditions=[])
    assert s.holding("NVDA")["position_gbp"] == 2500.0 and s.holding("NVDA")["conditions"] == []
    s.save_checks("NVDA", "2026-11-09T10:00:00+00:00", "r1", [{"index": 0, "status": "holding"}])
    s.save_checks("NVDA", "2026-11-10T10:00:00+00:00", "r2", [{"index": 0, "status": "at_risk"}])
    assert s.last_checks("NVDA")["report_id"] == "r2"


def test_the_thesis_desk_sees_only_the_conditions_and_the_evidence():
    from types import SimpleNamespace
    from desks.thesis import run_thesis_check
    seen = {}

    class AI:
        def call(self, **k):
            seen.update(k)
            return {"results": [{"index": 0, "status": "at_risk", "evidence": "Microsoft said capex growth will slow",
                                 "source": "reuters.com", "date": "2026-11-04", "reason": "A hyperscaler flagged slower capex."},
                                {"index": 1, "status": "holding", "evidence": "", "source": "", "date": "", "reason": "none"}]}
    news = SimpleNamespace(items=[SimpleNamespace(headline="Microsoft says capex growth will slow", published="2026-11-04",
                                                  source="reuters.com", url="https://x", summary="s", quality="Trusted")])
    rep = SimpleNamespace(news=news, research=None, company=None, ticker="NVDA", report_id="r")
    results, log = run_thesis_check(AI(), "r", rep, ["Two of META, AMZN, GOOGL guide 2027 capex down", "NVDA misses guidance"])
    body = seen["content"]
    assert "capex" in body and "thesis" not in body.lower().replace("thesis check", "") and "position" not in body.lower()
    assert [r["status"] for r in results] == ["at_risk", "holding"]
    assert results[0]["source"] == "reuters.com"


# --- earnings preview ------------------------------------------------------------------------------------------------
def _closes(days=range(1, 29), base=100.0, jump_after: dict | None = None):
    rows, px = [], base
    for d in days:
        px *= 1 + (jump_after or {}).get(f"2026-10-{d:02d}", 0.0)
        rows.append({"date": f"2026-10-{d:02d}", "close": px})
    return rows


def test_a_reaction_uses_the_session_the_company_reported_in():
    from engine.earnings import _closes as c, reaction
    rows = _closes(jump_after={"2026-10-11": 0.10})      # the price jumps on the 11th
    closes = c(rows)
    amc = reaction("2026-10-10", "amc", closes)          # reported after the close on the 10th: reaction is the 11th
    assert amc["move"] == pytest.approx(0.10) and amc["basis"] == "after the close"
    bmo = reaction("2026-10-11", "bmo", closes)          # reported before the open on the 11th
    assert bmo["move"] == pytest.approx(0.10) and bmo["from"] == "2026-10-10"
    unknown = reaction("2026-10-10", None, closes)       # timing unknown: the two-session move, and it says so
    assert unknown["move"] == pytest.approx(0.10) and "timing unknown" in unknown["basis"]
    assert reaction("2026-10-01", "amc", closes[1:]) is None   # no close before the date: cannot be computed


def test_last_eight_moves_skip_unreported_quarters_and_carry_the_eps_surprise():
    from datetime import date
    from engine.earnings import last_moves, move_summary
    hist = [{"date": f"2026-10-{d:02d}", "epsActual": 1.1, "epsEstimated": 1.0} for d in (5, 8, 12, 15, 18, 20, 22, 24, 26)]
    hist.append({"date": "2026-10-27", "epsActual": None, "epsEstimated": 1.2})   # not reported yet
    moves = last_moves(hist, {}, _closes(), 8, today=date(2026, 10, 28))
    assert len(moves) == 8 and moves[0]["date"] == "2026-10-26"                  # newest first, the 5th is left out
    assert moves[0]["surprise"] == pytest.approx(0.10)
    s = move_summary(moves)
    assert s["n"] == 8 and s["mean_abs"] >= 0 and move_summary([]) is None


def test_the_preview_opens_only_within_14_days():
    from datetime import date
    from engine.earnings import within_window
    assert within_window("2026-11-17", date(2026, 11, 9)) == 8
    assert within_window("2026-12-17", date(2026, 11, 9)) is None and within_window(None, date(2026, 11, 9)) is None
    assert within_window("2026-11-09", date(2026, 11, 9)) == 0 and within_window("2026-11-08", date(2026, 11, 9)) is None


def test_key_numbers_come_from_the_filing_and_keep_their_quotes():
    from engine.earnings import key_numbers
    data = {"business": {"volume_kpi": {"name": "Data Center revenue", "quote": "Data Center revenue was $115bn"},
                         "segments": [{"name": "Graphics", "revenue_millions": 14000, "quote": "g"},
                                      {"name": "Compute & Networking", "revenue_millions": 116000, "quote": "c"}]},
            "risks": {"guidance": [{"metric": "Revenue", "guidance_text": "$54bn plus or minus 2%", "quote": "q"}]}}
    out = key_numbers(data)
    assert [w["label"] for w in out] == ["Data Center revenue", "Compute & Networking revenue", "Graphics revenue"]
    assert key_numbers(None) == [] and key_numbers(data, limit=4)[-1]["label"].startswith("Guidance")


def test_the_preview_builder_states_what_is_missing_and_never_invents_an_options_move():
    from datetime import date
    from types import SimpleNamespace
    from core.cache import Cached
    from desks.earnings_preview import build_preview
    from datetime import datetime, timezone

    def c(x):
        return Cached(x, datetime(2026, 11, 9, tzinfo=timezone.utc), False, "k", "earnings")
    rows = [{"date": "2026-11-17", "epsActual": None, "epsEstimated": 1.31, "revenueEstimated": 54e9}] + \
           [{"date": f"2026-10-{d:02d}", "epsActual": 1.1, "epsEstimated": 1.0} for d in (8, 12, 15)]
    market = SimpleNamespace(
        finnhub=SimpleNamespace(call=lambda *a, **k: c({"earningsCalendar": [{"date": "2026-11-17", "hour": "amc"},
                                                                            {"date": "2026-10-12", "hour": "bmo"}]})),
        fmp=SimpleNamespace(call=lambda *a, **k: c(rows)),
        price_history=lambda s, start: SimpleNamespace(available=True, data=_closes()))
    svc = SimpleNamespace(market=market)
    rep = SimpleNamespace(ticker="NVDA", research=None, news=None,
                          company=SimpleNamespace(market=SimpleNamespace(next_earnings={"date": "2026-11-17", "eps_estimate": 1.31})))
    p = build_preview(rep, svc, today=date(2026, 11, 9))
    assert p["days"] == 8 and p["session"] == "after the US market close" and p["consensus"]["revenue"] == 54e9
    assert p["options_implied_move"] is None and any("Options-implied move: not available" in n for n in p["notes"])
    assert len(p["moves"]) == 3 and p["summary"]["n"] == 3
    far = build_preview(rep, svc, today=date(2026, 10, 1))
    assert far["days"] == 47 and "opens 14 days before" in far["notes"][0] and "moves" not in far
    rep.company.market.next_earnings = None
    assert "No earnings calendar entry" in build_preview(rep, svc)["notes"][0]


# --- cyclical price deck ---------------------------------------------------------------------------------------------
def _series(values, start_year=2016):
    return [(f"{start_year + i // 12}-{i % 12 + 1:02d}-01", v) for i, v in enumerate(values)]


def test_deck_summary_gives_trend_change_and_position_in_the_range():
    from engine.price_deck import summarise
    up = summarise(_series([100 + i for i in range(120)]))
    assert up["trend"] == "rising" and up["position"] > 0.99 and up["change_12m"] == pytest.approx(219 / 207 - 1)
    down = summarise(_series([300 - i for i in range(120)]))
    assert down["trend"] == "falling" and down["position"] < 0.01 and down["months"] == 120
    flat = summarise(_series([100.0] * 60))
    assert flat["trend"] == "flat" and flat["position"] == pytest.approx(0.5)
    assert summarise(_series([100.0] * 12)) is None                    # under two years: no deck, never a guess
    assert summarise([("2026-01-01", None)] * 40) is None


def test_deck_places_the_margin_target_between_median_and_p90():
    from engine.price_deck import target_margin
    assert target_margin(0.20, 0.50, None) == pytest.approx(0.35)      # no deck: half way, as before
    assert target_margin(0.20, 0.50, 0.0) == pytest.approx(0.20) and target_margin(0.20, 0.50, 1.0) == pytest.approx(0.50)
    assert target_margin(0.20, 0.50, 7.0) == pytest.approx(0.50)       # clamped


def test_only_a_memory_specific_deck_moves_the_valuation_margin():
    from engine.valuation import _deck_target
    cyc = {"available": True, "median_margin": 0.20, "p90_margin": 0.50, "cycle_target_margin": 0.35}
    proxy = {"position": 0.0, "memory_specific": False}
    memory = {"position": 0.0, "memory_specific": True}
    assert _deck_target(cyc, None) == 0.35 and _deck_target(cyc, proxy) == 0.35   # a broad proxy is shown, not used
    assert _deck_target(cyc, memory) == pytest.approx(0.20)
    assert _deck_target({"available": False}, memory) is None


def test_the_deck_is_only_built_for_the_memory_and_storage_names():
    from datetime import date
    from types import SimpleNamespace
    from core.cache import Cached
    from datetime import datetime, timezone
    from desks.modelling import deck_text, price_deck_for
    payload = [[d, v] for d, v in _series([100 + i * 0.1 for i in range(130)], 2016)]
    svc = SimpleNamespace(fred=SimpleNamespace(series=lambda sid, start: Cached(payload, datetime(2026, 11, 9, tzinfo=timezone.utc),
                                                                                False, "k", "fred")))
    assert price_deck_for("NVDA", svc, date(2026, 11, 9)) is None and price_deck_for("KO", svc, date(2026, 11, 9)) is None
    for t in ("MU", "SNDK", "WDC", "STX"):
        d = price_deck_for(t, svc, date(2026, 11, 9))
        assert d and d["memory_specific"] is False and d["series"] == "PCU334413334413"
    assert "not DRAM or NAND" in deck_text(d) and "does not move the margin fade" in deck_text(d)

    def broken(*a, **k):
        raise RuntimeError("no FRED key")
    assert price_deck_for("MU", SimpleNamespace(fred=SimpleNamespace(series=broken)), date(2026, 11, 9)) is None


# --- AI capex tracker --------------------------------------------------------------------------------------------------
PRESS = ("<html><body><p>Operating income was $28.5 billion.</p><ul><li>We continue to expect 2026 cash capital "
         "expenditures to be approximately $220 billion.</li><li>Net cash used for investing activities increased by "
         "$19.9 billion, primarily due to capital expenditures.</li></ul><p>We anticipate 2026 capital expenditures, "
         "including principal payments on finance leases, to be in the range of $135-145 billion, narrowed from our "
         "prior outlook of $130-145 billion.</p><p>Aggregate net proceeds were $19.0 billion for general corporate "
         "purposes, including capital expenditures.</p></body></html>")


def test_capex_sentences_are_forward_looking_verbatim_and_carry_a_figure():
    from engine.capex import capex_statements
    out = capex_statements(PRESS)
    assert out == ["We continue to expect 2026 cash capital expenditures to be approximately $220 billion.",
                   "We anticipate 2026 capital expenditures, including principal payments on finance leases, to be in "
                   "the range of $135-145 billion, narrowed from our prior outlook of $130-145 billion."]
    assert capex_statements("Capital expenditures were $5 billion last quarter.") == []     # past, not guidance
    assert capex_statements("We expect strong demand.") == []                               # no capex, no figure
    assert capex_statements("") == []


def test_ai_revenue_share_uses_segments_then_kpis_and_attaches_above_30_percent():
    from engine.capex import qualifies
    nvda = {"business": {"segments": [{"name": "Compute & Networking", "revenue_millions": 116000},
                                      {"name": "Graphics", "revenue_millions": 14000}]}}
    ok, share, how = qualifies(nvda, 130000)
    assert ok and share == pytest.approx(116 / 130) and "Compute & Networking" in how
    ko = {"business": {"segments": [{"name": "Beverages", "revenue_millions": 40000}]}}
    assert qualifies(ko, 46000)[0] is False
    kpi = {"business": {"segments": [], "kpis": [{"name": "Data Center revenue", "value_text": "$115.2 billion"}]}}
    ok, share, how = qualifies(kpi, 200000)
    assert ok and share == pytest.approx(0.576) and how.startswith("KPI")
    no, share, why = qualifies({}, None)
    assert not no and share is None and "no data centre" in why
    edge = {"business": {"segments": [{"name": "Cloud", "revenue_millions": 30}, {"name": "Other", "revenue_millions": 70}]}}
    assert qualifies(edge, 100)[0] is False                                                  # exactly 30% is not above it


def test_capex_tracker_reads_the_release_then_the_periodic_report_and_flags_stale_ones(monkeypatch):
    from datetime import date
    from types import SimpleNamespace
    import desks.capex as cx
    filings = [{"form": "10-Q", "filing_date": "2026-06-01", "items": "", "description": "", "url": "https://sec/x/0001/q.htm"},
               {"form": "8-K", "filing_date": "2026-10-21", "items": "2.02,9.01", "description": "",
                "url": "https://sec/x/000162828026066700/m.htm"}]
    svc = SimpleNamespace(edgar=SimpleNamespace(cik_for=lambda t: 1 if t != "ZZZ" else None,
                                                recent_filings_fresh=lambda cik, forms: (filings, "now"),
                                                filing_documents=lambda cik, f: [{"name": "ex991.htm"}, {"name": "m.htm"}]))
    monkeypatch.setattr(cx, "_text", lambda s, url: PRESS if "ex991" in url else "nothing here")
    row = cx.company_capex(svc, "META", date(2026, 11, 11))
    assert [s["filed"] for s in row["statements"]] == ["2026-10-21", "2026-10-21"] and not row["statements"][0]["stale"]
    assert row["statements"][0]["url"].endswith("ex991.htm") and row["statements"][0]["age_days"] == 21
    # an earnings release with no capex sentence falls back to the 10-Q, which is old, so it is flagged stale
    monkeypatch.setattr(cx, "_text", lambda s, url: "nothing here" if "ex991" in url else PRESS)
    row = cx.company_capex(svc, "META", date(2026, 11, 11))
    assert row["statements"] and row["statements"][0]["form"] == "10-Q" and row["statements"][0]["stale"]
    monkeypatch.setattr(cx, "_text", lambda s, url: "nothing here")
    none = cx.company_capex(svc, "META", date(2026, 11, 11))
    assert none["statements"] == [] and "No forward-looking capex sentence" in none["notes"][0]
    assert "Filings unavailable" in cx.company_capex(svc, "ZZZ", date(2026, 11, 11))["notes"][0]


# --- track record: price after 1, 3 and 6 months ------------------------------------------------------------------------
def _call(rating, price=100.0, date_="2026-01-02", ticker="AAA"):
    return {"ticker": ticker, "call_date": date_, "price": price, "verdict": "Undervalued", "rating": rating,
            "fair_value": 150.0, "report_id": f"{ticker}-r"}


def test_direction_hit_follows_the_rating():
    from engine.track import direction_hit
    assert direction_hit("Buy", 0.05) is True and direction_hit("Strong Buy", -0.01) is False
    assert direction_hit("Sell", -0.2) is True and direction_hit("Strong Sell", 0.2) is False
    assert direction_hit("Hold", 0.09) is True and direction_hit("Hold", -0.11) is False
    assert direction_hit("Buy", None) is None and direction_hit("Not rated", 0.5) is None and direction_hit(None, 0.5) is None


def test_horizon_row_waits_for_each_date_and_compares_with_the_base_dcf():
    from datetime import date
    from engine.track import horizon_row
    prices = {"2026-02-01": 110.0, "2026-04-03": 130.0}
    row = horizon_row(_call("Buy"), lambda t, d: prices.get(d.isoformat()), date(2026, 5, 1), base_dcf=125.0)
    assert row["after"]["1m"]["price"] == 110.0 and row["after"]["1m"]["change"] == pytest.approx(0.10)
    assert row["after"]["1m"]["vs_base_dcf"] == pytest.approx(110 / 125 - 1) and row["after"]["1m"]["hit"] is True
    assert row["after"]["3m"]["price"] == 130.0 and row["after"]["3m"]["vs_base_dcf"] == pytest.approx(0.04)
    six = row["after"]["6m"]                                    # 2026-07-03 has not happened yet on 1 May
    assert six["elapsed"] is False and six["price"] is None and six["hit"] is None
    missing = horizon_row(_call("Buy"), lambda t, d: None, date(2026, 12, 31), base_dcf=None)
    assert missing["after"]["1m"]["elapsed"] and missing["after"]["1m"]["change"] is None and missing["base_dcf"] is None


def test_hit_rate_by_rating_counts_only_horizons_with_a_price_and_skips_unrated_calls():
    from datetime import date
    from engine.track import hit_rate_by_rating, horizon_row
    px = {"AAA": {"2026-02-01": 110.0, "2026-04-03": 90.0}, "BBB": {"2026-02-01": 80.0}, "CCC": {"2026-02-01": 150.0}}
    calls = [_call("Buy", ticker="AAA"), _call("Buy", ticker="BBB"), _call("Sell", ticker="CCC"), _call(None, ticker="DDD")]
    rows = [horizon_row(c, lambda t, d: px.get(t, {}).get(d.isoformat()), date(2026, 5, 1), None) for c in calls]
    rates = hit_rate_by_rating(rows)
    assert set(rates) == {"Buy", "Sell"}
    assert rates["Buy"]["1m"] == {"calls": 2, "hits": 1, "rate": 0.5}   # AAA +10% hit, BBB -20% miss
    assert rates["Buy"]["3m"]["calls"] == 1 and rates["Buy"]["3m"]["rate"] == 0.0
    assert rates["Sell"]["1m"]["rate"] == 0.0 and rates["Buy"]["6m"]["rate"] is None


# --- stock pitch ---------------------------------------------------------------------------------------------------------
def _pitch_report(with_md=True):
    from types import SimpleNamespace
    rep = fake_report("KO", price_factor=0.9)
    rep.model.inputs = SimpleNamespace(price=SimpleNamespace(period="2026-11-09T21:00:00+00:00", source="FMP"),
                                       risk_free=rep.model.inputs.risk_free, consensus=[])
    rep.company.profile = SimpleNamespace(name="Test Co", ticker="KO", exchange="NYSE", sic_description="Beverages")
    rep.company.historicals = SimpleNamespace(fy_labels=["FY2024", "FY2025"], ltm=None)
    rep.valuation_date = "2026-11-09"
    rep.md = SimpleNamespace(rating="Hold", view={
        "thesis": "A steady compounder priced fairly. Second sentence is dropped.",
        "reasoning_lines": ["Margins are stable.", "Cash returns are covered.", "Valuation is not demanding.", "Extra line."],
        "key_risks": [{"risk": "Sugar taxes", "quote": "Taxes on sugary drinks may reduce demand."},
                      {"risk": "FX", "quote": ""}, {"risk": "Water", "quote": "Water scarcity"}, {"risk": "Fourth", "quote": ""}],
        "what_would_change_view": ["Volume growth turning negative for two years"]}) if with_md else None
    return rep


def test_pitch_is_one_page_with_chart_the_users_thesis_and_their_exit_conditions():
    import re
    from exports.pitch import build_pitch
    rep = _pitch_report()
    closes = [(f"2026-{1 + i // 30:02d}-{1 + i % 28:02d}", 90 + i * 0.1) for i in range(300)]
    pdf = build_pitch(rep, closes, {"thesis": "Pricing power outruns inflation. More text.",
                                    "conditions": ["Volume falls two years running", "Net debt above 3x EBITDA"]})
    assert pdf.startswith(b"%PDF") and len(re.findall(rb"/Type\s*/Page[^s]", pdf)) == 1
    plain = build_pitch(_pitch_report(), [], None)                  # no history, no holding: still one page
    assert len(re.findall(rb"/Type\s*/Page[^s]", plain)) == 1


def test_pitch_text_pieces_prefer_the_users_words_and_say_what_is_missing():
    from exports.pitch import first_sentence, shorten
    assert first_sentence("One. Two.") == "One." and first_sentence("") == ""
    assert shorten("x" * 300, 50).endswith("…") and len(shorten("x" * 300, 50)) == 50
    from exports.pitch import price_chart
    d = price_chart([], {}, 400, 100)
    assert len(d.contents) == 1                                      # only the 'No price history' note
    d = price_chart([("2026-01-01", 10.0), ("2026-01-02", 12.0)], {"Base DCF": 11.0, "Bear DCF": None}, 400, 100)
    assert len(d.contents) >= 5


def test_pitch_works_for_a_report_with_no_md_and_no_dcf():
    import re
    from exports.pitch import build_pitch
    rep = _pitch_report(with_md=False)
    rep.model.financial = object()                                   # a bank: no DCF
    pdf = build_pitch(rep, [], None)
    assert len(re.findall(rb"/Type\s*/Page[^s]", pdf)) == 1
