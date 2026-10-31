"""Phase 11: impact analysis, offline. Code does every calculation: repricing the model for a proposed driver
change, the news-adjusted fair value, the abnormal return since the news and the "priced in?" call. The AI only
proposes; code enforces bounds, the Unverified-source rule and verbatim sensitivity quotes."""
import json
from datetime import date
from types import SimpleNamespace

import pytest

from core.cache import Cache
from desks.ai import AIClient, CostLedger
from desks.impact import impact_payload, run_impact, run_news_view
from desks.news import NewsItem, NewsResult
from engine.news_impact import Change, check_change, overrides_for, priced_in, reprice, return_since
from engine.valuation import value_company
from engine.verdict import blend
from tests.engine_fixtures import engine_inputs


@pytest.fixture(scope="module")
def model():
    ei = engine_inputs("GRAB")
    v = value_company(ei)
    verdict = blend({"dcf": v.per_us_share(v.scenario_value), "comps": 5.0, "history": None}, ei.price.value)
    profile = SimpleNamespace(ticker="GRAB", sic="7372", name="Grab Holdings")
    company = SimpleNamespace(profile=profile, historicals=ei.historicals, analysis=ei.analysis)
    return SimpleNamespace(valuation=v, inputs=ei, verdict=verdict, company=company)


# --- repricing ---------------------------------------------------------------------------------------------------
def test_reprice_without_changes_is_the_base(model):
    r = reprice(model, {})
    assert r.fair_value == pytest.approx(model.verdict.fair_value)
    assert r.year1_nopat_per_share is not None


@pytest.mark.parametrize("change,direction", [
    (Change("operating_margin", 2, 3), 1), (Change("wacc", 0.5), -1),
    (Change("scenario_probability", 10), 1), (Change("scenario_probability", -10), -1),
    (Change("operating_margin", -2, 1), -1)])
def test_each_driver_moves_fair_value_the_right_way(model, change, direction):
    base = reprice(model, {}).fair_value
    ov, prob = overrides_for(model, [change])
    moved = reprice(model, ov, prob).fair_value
    assert (moved - base) * direction > 0


@pytest.mark.parametrize("sales_to_capital", [0.5, 8.0])
def test_growth_adds_value_only_above_the_cost_of_capital(model, sales_to_capital):
    """Faster growth is not automatically worth more. With terminal ROIC = WACC, extra revenue is worth more only if
    the capital it needs earns above WACC: return on new capital = after-tax margin x sales-to-capital. At 0.5 GRAB's
    reinvestment earns far below WACC (growth destroys value); at 8 it earns far above (growth creates value)."""
    plan, wacc = model.valuation.plan, model.valuation.wacc.wacc.value
    assert plan.terminal_roic.value == pytest.approx(wacc)
    fixed = {"sales_to_capital": sales_to_capital}
    base = reprice(model, fixed).fair_value
    ov, prob = overrides_for(model, [Change("revenue_growth", 3, 2)])
    moved = reprice(model, {**ov, **fixed}, prob).fair_value
    m, t = plan.path("operating_margin"), plan.path("tax_rate")
    returns = [m[k] * (1 - t[k]) * sales_to_capital for k in range(len(m))]
    assert all(r < wacc for r in returns) or all(r > wacc for r in returns)  # the case is unambiguous
    assert (moved > base) == (returns[0] > wacc)


def test_margin_shift_only_touches_the_years_given(model):
    ov, _ = overrides_for(model, [Change("operating_margin", 2, 2)])
    assert ov["margin_shift"][:3] == [0.02, 0.02, 0.0]
    base_path = model.valuation.plan.path("operating_margin")
    from dataclasses import replace
    v2 = value_company(replace(model.inputs, overrides={**model.inputs.overrides, **ov}))
    new_path = v2.plan.path("operating_margin")
    assert new_path[0] == pytest.approx(base_path[0] + 0.02) and new_path[2] == pytest.approx(base_path[2])
    assert model.valuation.plan.path("operating_margin") == base_path  # the base valuation is untouched


def test_changes_combine_per_driver(model):
    g = model.valuation.plan.path("revenue_growth")
    ov, prob = overrides_for(model, [Change("revenue_growth", 1, 1), Change("revenue_growth", 2, 2),
                                     Change("scenario_probability", 5), Change("scenario_probability", 5)])
    assert ov["revenue_growth"][0] == pytest.approx(g[0] + 0.03) and ov["revenue_growth"][1] == pytest.approx(g[1] + 0.02)
    assert prob == pytest.approx(0.10)


def test_bounds():
    assert check_change(Change("revenue_growth", 3)) is None
    assert "beyond" in check_change(Change("revenue_growth", 15))
    assert "beyond" in check_change(Change("wacc", -2))
    assert check_change(Change("none", 0)) == "no model driver"
    assert check_change(Change("operating_margin", 0)) == "no change proposed"


# --- priced in? ----------------------------------------------------------------------------------------------------
def series(*pts):
    return [{"date": d, "close": c, "adj_close": None} for d, c in pts]


STOCK = series(("2026-10-20", 100.0), ("2026-10-21", 96.0), ("2026-10-28", 95.0))
SPY = series(("2026-10-20", 500.0), ("2026-10-21", 505.0), ("2026-10-28", 505.0))
XLK = series(("2026-10-20", 200.0), ("2026-10-21", 200.0), ("2026-10-28", 202.0))


def test_return_since_uses_the_close_before_the_news():
    r, a, b = return_since(STOCK, "2026-10-21")
    assert r == pytest.approx(-0.05) and (a, b) == ("2026-10-20", "2026-10-28")
    assert return_since(STOCK, "2026-10-29") is None  # nothing traded since


@pytest.mark.parametrize("impact,verdict", [(-0.06, "priced in"), (-0.12, "partly priced in"),
                                            (-0.40, "not priced in"), (0.06, "market moved the other way"),
                                            (0.001, "no material impact to price"), (None, "not comparable")])
def test_priced_in_verdicts(impact, verdict):
    p = priced_in(STOCK, SPY, XLK, "2026-10-21", impact)
    assert p.verdict == verdict
    assert p.abnormal_vs_market == pytest.approx(-0.05 - 0.01)
    assert p.abnormal_vs_sector == pytest.approx(-0.05 - 0.01)


def test_priced_in_too_recent():
    assert priced_in(STOCK, SPY, XLK, "2026-10-29", -0.05).verdict == "too recent to judge"


# --- the desk end to end -----------------------------------------------------------------------------------------
class FakeClient:
    def __init__(self, answers):
        self.answers, self.calls = list(answers), []
        self.messages = SimpleNamespace(create=self._create)
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **kw):
        self.calls.append(kw)
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=json.dumps(self.answers.pop(0)))],
                               stop_reason="end_turn", model=kw["model"],
                               usage=SimpleNamespace(input_tokens=1000, output_tokens=100, cache_read_input_tokens=0,
                                                     cache_creation_input_tokens=0, server_tool_use=None))


def analysis(iid, driver="none", change=0.0, years=1, quantifiable=False, corroborated=(), quote=""):
    return {"item_id": iid, "chain": "Reaches revenue through ride demand.", "driver": driver, "change": change,
            "years": years, "quantifiable": quantifiable,
            "qualitative_reason": "" if quantifiable else "Too early to size.", "sensitivity_quote": quote,
            "corroborated_by": list(corroborated), "duration": "temporary", "bull_reading": "Demand holds up.",
            "bear_reading": "Demand weakens.", "more_convincing": "bear", "why": "The data point is weak.",
            "watch": [{"event": "Quarterly results", "date": "not disclosed"}]}


def news_item(head, quality, published="2026-10-21", tier="company"):
    return NewsItem(head, tier, published, "x.com", quality, f"https://x.com/{len(head)}", "What happened.")


class Market:
    def price_history(self, symbol, start):
        return SimpleNamespace(available=True, data={"GRAB": STOCK, "SPY": SPY, "XLK": XLK}[symbol])


def test_run_impact_applies_the_rules(model, tmp_path):
    items = [news_item("Regulator blocks deal", "Trusted"), news_item("Blog says margins collapse", "Unverified"),
             news_item("Forum post on growth", "Unverified"), news_item("Huge claim", "Established"),
             news_item("Rates story", "Trusted", tier="macro")]
    news = NewsResult(as_of="2026-10-29T12:00:00+00:00", items=items)
    answer = {"items": [
        analysis("N1", "operating_margin", -1.0, 2, True),
        analysis("N2", "operating_margin", -2.0, 1, True),                    # Unverified, uncorroborated
        analysis("N3", "operating_margin", -0.5, 1, True, corroborated=["N1", "N3"]),  # same fact as N1
        analysis("N4", "revenue_growth", 25.0, 1, True),                      # beyond the bound
        analysis("N5", "wacc", 0.2, 1, True, quote="this sentence is not in the filing"),
        analysis("N9", "wacc", 0.2, 1, True)]}                                # unknown id: ignored
    fake = FakeClient([answer, answer])  # the guard regenerates once: N5's quote is not in the filing
    client = AIClient("k", Cache(tmp_path / "c"), CostLedger(tmp_path / "d.sqlite", 1.0, 5.0), client=fake)
    svc = SimpleNamespace(market=Market())
    res = run_impact(client, svc, "r", model, news, {"price": 4.0}, None, "The filing text.")
    by = {i.item_id: i for i in res.items}
    assert set(by) == {"N1", "N2", "N3", "N4", "N5"}
    assert by["N1"].quantified and by["N1"].fair_value_effect < 0
    assert not by["N2"].quantified and "Unverified" in by["N2"].reason
    assert not by["N3"].quantified and "counted once, through N1" in by["N3"].reason  # never double-counted
    assert not by["N4"].quantified and "beyond" in by["N4"].reason
    assert by["N5"].quantified and by["N5"].sensitivity_quote == ""  # the guard dropped the invented quote
    assert len(fake.calls) == 2 and any("Impact analyst" in g for g in res.guard_log)
    assert by["N1"].priced.verdict in ("priced in", "partly priced in", "not priced in", "market moved the other way",
                                       "no material impact to price")
    # the news-adjusted fair value applies every accepted change together; the base is unchanged
    ov, prob = overrides_for(model, [Change("operating_margin", -1.0, 2), Change("wacc", 0.2, 1)])
    assert res.adjusted_fair_value == pytest.approx(reprice(model, ov, prob).fair_value)
    assert res.base_fair_value == model.verdict.fair_value
    assert res.benchmarks == {"market": "SPY", "sector": "XLK"}
    p = impact_payload(res)
    assert p["news_adjusted_fair_value"] == round(res.adjusted_fair_value, 2) and len(p["items"]) == 5

    # the MD's news summary is written from those computed figures (and passes the number guard)
    view = {"what_news_means": "The news trims fair value modestly.", "scenario_shift": "bear",
            "scenario_why": "The regulator decision weighs on growth.", "changes_rating": False,
            "rating_why": "The effect is small and temporary."}
    client._client = FakeClient([view])
    run_news_view(client, "r", res, "Hold", "Medium")
    assert res.view == view
    sent = client._client.calls[0]["messages"][0]["content"]
    assert "news_adjusted_fair_value" in sent and "Hold" in sent


def test_no_news_means_no_ai_call(model, tmp_path):
    fake = FakeClient([])
    client = AIClient("k", Cache(tmp_path / "c"), CostLedger(tmp_path / "d.sqlite", 1.0, 5.0), client=fake)
    res = run_impact(client, SimpleNamespace(market=Market()), "r", model, NewsResult(as_of="t"), {}, None, "")
    assert res.items == [] and res.adjusted_fair_value == model.verdict.fair_value and not fake.calls


def test_numbers_in_the_news_may_be_quoted_but_not_invented(model, tmp_path):
    items = [NewsItem("Phillips 66 posts record profit as refining margin hits $42", "industry", "2026-10-21",
                      "reuters.com", "Trusted", "https://reuters.com/p66", "Profit was $3bn.")]
    ok = analysis("N1")
    ok["chain"] = "Phillips 66 reported a $42 refining margin, which signals strong sector margins."
    bad = analysis("N1")
    bad["chain"] = "Profit was $3bn, so margins could add more."  # a figure from the desk's summary, not the source
    fake = FakeClient([{"items": [ok]}])
    client = AIClient("k", Cache(tmp_path / "c"), CostLedger(tmp_path / "d.sqlite", 1.0, 5.0), client=fake)
    res = run_impact(client, SimpleNamespace(market=Market()), "r", model, NewsResult(as_of="t", items=items), {},
                     None, "")
    assert len(fake.calls) == 1 and not res.guard_log and "$42" in res.items[0].chain
    fake2 = FakeClient([{"items": [bad]}, {"items": [bad]}])
    client2 = AIClient("k", Cache(tmp_path / "c2"), CostLedger(tmp_path / "d2.sqlite", 1.0, 5.0), client=fake2)
    res2 = run_impact(client2, SimpleNamespace(market=Market()), "r", model, NewsResult(as_of="t", items=items), {},
                      None, "")
    assert len(fake2.calls) == 2 and "$3bn" not in res2.items[0].chain


def test_priced_in_uses_one_window_when_a_benchmark_lags():
    stock = STOCK + series(("2026-10-29", 90.0))
    p = priced_in(stock, SPY, XLK, "2026-10-21", -0.05)
    assert p.window == "close 2026-10-20 to close 2026-10-28" and p.abnormal_vs_sector == pytest.approx(-0.06)


def test_unverified_needs_a_backer_on_the_same_driver(model, tmp_path):
    items = [news_item("Trusted story", "Trusted"), news_item("Blog story", "Unverified")]
    answer = {"items": [analysis("N1", "operating_margin", -1.0, 1, True),
                        analysis("N2", "revenue_growth", 2.0, 1, True, corroborated=["N1"])]}
    client = AIClient("k", Cache(tmp_path / "c"), CostLedger(tmp_path / "d.sqlite", 1.0, 5.0),
                      client=FakeClient([answer]))
    res = run_impact(client, SimpleNamespace(market=Market()), "r", model, NewsResult(as_of="t", items=items), {},
                     None, "")
    n2 = next(i for i in res.items if i.item_id == "N2")
    assert not n2.quantified and "no Trusted or Established item sizing the same effect" in n2.reason


def test_combined_changes_are_capped_and_breaking_the_dcf_is_refused(model):
    from engine.news_impact import RepriceError, capped
    out, notes = capped([Change("wacc", 1.0), Change("wacc", 1.0), Change("revenue_growth", 2.0)])
    assert sum(c.change for c in out if c.driver == "wacc") == pytest.approx(1.5) and notes
    g, w = model.valuation.plan.terminal_growth.value, model.valuation.wacc.wacc.value
    with pytest.raises(RepriceError):  # WACC cut to just above terminal growth breaks the bull scenario
        reprice(model, {"wacc": g + 0.004})


def test_wacc_change_builds_on_the_users_override(model):
    from dataclasses import replace
    m2 = SimpleNamespace(**{**model.__dict__, "inputs": replace(model.inputs, overrides={"wacc": 0.12})})
    ov, _ = overrides_for(m2, [Change("wacc", 0.5)])
    assert ov["wacc"] == pytest.approx(0.125)


def test_watch_dates_must_be_dates(model, tmp_path):
    a = analysis("N1")
    a["watch"] = [{"event": "Results", "date": "after revenue hits $5bn"}, {"event": "Vote", "date": "Q4 2026"}]
    client = AIClient("k", Cache(tmp_path / "c"), CostLedger(tmp_path / "d.sqlite", 1.0, 5.0),
                      client=FakeClient([{"items": [a]}]))
    res = run_impact(client, SimpleNamespace(market=Market()), "r", model,
                     NewsResult(as_of="t", items=[news_item("Story", "Trusted")]), {}, None, "")
    assert [w["date"] for w in res.items[0].watch] == ["not disclosed", "Q4 2026"]


def test_shifts_start_at_the_first_forecast_year(model):
    """An ended but unreported fiscal year comes first in the plan; a 'year 1' news shift must skip it."""
    from dataclasses import replace
    plan = replace(model.valuation.plan, skipped=["FY2026"])
    m2 = SimpleNamespace(**{**model.__dict__, "valuation": replace(model.valuation, plan=plan)})
    ov, _ = overrides_for(m2, [Change("operating_margin", 2, 1)])
    assert ov["margin_shift"][:3] == [0.0, 0.02, 0.0]
