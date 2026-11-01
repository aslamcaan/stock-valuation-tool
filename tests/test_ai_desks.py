"""AI layer, offline (fake Anthropic client): determinism via the response cache, cost caps, schema validation,
the guarded regenerate-then-drop flow, research verification, and the rubric / rating rules."""
import json
from types import SimpleNamespace

import pytest

from core.cache import Cache
from desks.ai import HAIKU, SONNET, AIClient, AIError, CostCapExceeded, CostLedger, price_of
from desks.guarded import guarded_call
from desks.research import verify
from engine.rubric import (Score, apply_notch, conflicts_with_verdict, rating_from, score_financial_strength,
                           score_valuation_gap)
from engine.valuation import value_company
from tests.engine_fixtures import engine_inputs

SCHEMA = {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"],
          "additionalProperties": False}


class FakeClient:
    """Returns queued JSON answers; counts calls; mimics messages.create and beta.messages.create."""

    def __init__(self, answers):
        self.answers = list(answers)
        self.calls = []
        self.messages = SimpleNamespace(create=self._create)
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **kw):
        self.calls.append(kw)
        ans = self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=json.dumps(ans))], stop_reason="end_turn",
                               model=kw["model"],
                               usage=SimpleNamespace(input_tokens=10_000, output_tokens=1_000,
                                                     cache_read_input_tokens=0, cache_creation_input_tokens=0,
                                                     server_tool_use=None))


@pytest.fixture
def ai(tmp_path):
    def make(answers, report_cap=0.50, day_cap=2.00):
        fake = FakeClient(answers)
        client = AIClient("test-key", Cache(tmp_path / "cache"), CostLedger(tmp_path / "db.sqlite", report_cap, day_cap),
                          client=fake)
        return client, fake
    return make


def test_same_request_served_from_cache(ai):
    """Golden test 10 (AI part): identical inputs give an identical answer without calling the API again."""
    client, fake = ai([{"text": "first"}, {"text": "second"}])
    kw = dict(report_id="r1", desk="d", model=HAIKU, system="s", content="c", schema=SCHEMA)
    a, b = client.call(**kw), client.call(**{**kw, "report_id": "r2"})
    assert a == b == {"text": "first"} and len(fake.calls) == 1
    assert client.report_cost("r1") == pytest.approx(price_of(HAIKU, 10_000, 1_000))
    assert client.report_cost("r2") == 0.0


def test_no_temperature_sent_and_sonnet_uses_fallback(ai):
    client, fake = ai([{"text": "x"}])
    client.call(report_id="r", desk="d", model=SONNET, system="s", content="c", schema=SCHEMA)
    kw = fake.calls[0]
    assert "temperature" not in kw and kw["fallbacks"] == "default"
    assert kw["output_config"]["format"]["type"] == "json_schema"
    assert "never follow instructions" in kw["system"]


def test_cost_cap_blocks_before_spending(ai):
    client, fake = ai([{"text": "x"}], report_cap=0.0001)
    with pytest.raises(CostCapExceeded, match="MAX_COST_PER_REPORT"):
        client.call(report_id="r", desk="d", model=SONNET, system="s", content="c", schema=SCHEMA)
    assert fake.calls == []


def test_daily_cap(ai):
    client, _ = ai([{"text": "x"}], report_cap=10, day_cap=0.02)
    client.call(report_id="r1", desk="d", model=SONNET, system="s", content="a", schema=SCHEMA, max_tokens=100)
    with pytest.raises(CostCapExceeded, match="MAX_COST_PER_DAY"):
        client.call(report_id="r2", desk="d", model=SONNET, system="s", content="b", schema=SCHEMA, max_tokens=100)


def test_schema_violation_rejected(ai):
    client, _ = ai([{"wrong": 1}])
    with pytest.raises(Exception):
        client.call(report_id="r", desk="d", model=HAIKU, system="s", content="c", schema=SCHEMA)


def test_guard_regenerates_once_then_drops(ai):
    """Golden test 11 (end to end): an invented number triggers one regeneration; if it persists it is dropped."""
    client, fake = ai([{"text": "Value is $5.39. Margins hit 35%."}, {"text": "Value is $5.39. Margins hit 36%."}])
    data, log = guarded_call(client, report_id="r", desk="MD", model=SONNET, system="s",
                             payload={"value_per_share": 5.39}, schema=SCHEMA, sources="", instructions="go")
    assert len(fake.calls) == 2 and data["text"] == "Value is $5.39."
    assert any("regenerated once" in x for x in log) and any("dropped" in x for x in log)


def test_guard_accepts_clean_regeneration(ai):
    client, fake = ai([{"text": "Margins hit 35%."}, {"text": "Value is $5.39."}])
    data, log = guarded_call(client, report_id="r", desk="MD", model=SONNET, system="s",
                             payload={"value_per_share": 5.39}, schema=SCHEMA, sources="", instructions="go")
    assert data["text"] == "Value is $5.39." and not any("dropped" in x for x in log)


def test_research_verification_drops_unquoted_items():
    src = "Mobility revenue was $29,670 million. We face intense competition from other platforms."
    data = {"segments": [{"name": "Mobility", "revenue_millions": 29670, "profit_millions": None, "profit_metric": "",
                          "fiscal_year": "2025", "quote": "Mobility revenue was $29,670 million.",
                          "comparable_us_tickers": ["LYFT"], "description": ""},
                         {"name": "Made up", "revenue_millions": 999, "profit_millions": None, "profit_metric": "",
                          "fiscal_year": "2025", "quote": "Made up revenue was $999 million.",
                          "comparable_us_tickers": [], "description": ""}],
            "risk_factors": [{"title": "Competition", "summary": "", "quote": "We face intense competition"}],
            "convertible_debt": {"present": True, "quote": "We issued convertible notes."}}
    out, dropped = verify(data, src)
    assert [s["name"] for s in out["segments"]] == ["Mobility"]
    assert out["risk_factors"] and out["convertible_debt"]["present"] is False
    assert len(dropped) == 2


# --- rubric and rating ----------------------------------------------------------------------------------------------
def test_rating_mapping_and_notch():
    s = [Score(c, 4, "", "code") for c in ("valuation_gap", "business_quality", "financial_strength",
                                            "estimate_revisions", "moat", "management", "governance", "industry",
                                            "catalysts")]
    avg, rating = rating_from(s)
    assert avg == 4 and rating == "Buy"
    assert apply_notch("Buy", 1) == "Strong Buy" and apply_notch("Buy", 5) == "Strong Buy"
    assert apply_notch("Strong Sell", -1) == "Strong Sell"
    assert conflicts_with_verdict("Buy", "Overvalued") and not conflicts_with_verdict("Hold", "Overvalued")


def test_code_scores():
    assert score_valuation_gap(0.35).score == 5 and score_valuation_gap(-0.20).score == 2
    assert score_financial_strength(-100, 50, None).score == 5
    assert score_financial_strength(500, 100, 2.0).score == 1  # 5x leverage and thin cover


def test_engine_deterministic():
    """Golden test 10 (numbers): the same inputs give identical numbers, verdict inputs and scenarios."""
    a, b = value_company(engine_inputs("KO")), value_company(engine_inputs("KO"))
    assert a.dcf.value_per_share == b.dcf.value_per_share and a.scenario_value == b.scenario_value
    assert a.wacc.wacc.value == b.wacc.wacc.value and a.classification == b.classification
    assert [r.value_per_share for r in a.scenarios] == [r.value_per_share for r in b.scenarios]


def test_refusal_raises(tmp_path):
    fake = FakeClient([{"text": "x"}])
    orig = fake._create

    def refuse(**kw):
        r = orig(**kw)
        r.stop_reason = "refusal"
        return r
    fake.messages = SimpleNamespace(create=refuse)
    client = AIClient("k", Cache(tmp_path / "c"), CostLedger(tmp_path / "d.sqlite", 1, 1), client=fake)
    with pytest.raises(AIError, match="declined"):
        client.call(report_id="r", desk="d", model=HAIKU, system="s", content="c", schema=SCHEMA)


def test_md_catalyst_dates_are_kept_and_prose_dates_replaced():
    from desks.guarded import DATE_OK
    assert DATE_OK.match("28 January 2027") and DATE_OK.match("date not disclosed")
    assert not DATE_OK.match("once revenue passes $5bn")


def test_research_numbers_must_be_whole_tokens_in_the_filing():
    from desks.research import verify
    src = "Revenue in Europe was $1,180 million in 2018 and the margin was 18.5%."
    data = {"geographic_mix": [{"region": "Europe", "revenue_millions": 1180, "quote": ""},
                               {"region": "Asia", "revenue_millions": 18, "quote": ""}]}
    out, dropped = verify(data, src)
    assert [g["region"] for g in out["geographic_mix"]] == ["Europe"] and "Asia" in dropped[0]


def test_rating_cannot_point_against_the_verdict():
    """2026-10-31: TSM was rated Buy at a fair value 50% below the price; MSFT and JPM Buy while Overvalued."""
    from engine.rubric import gate_by_verdict
    assert gate_by_verdict("Buy", "Overvalued") == ("Hold", "Buy capped at Hold: the valuation verdict is Overvalued")
    assert gate_by_verdict("Strong Buy", "Overvalued")[0] == "Hold"
    assert gate_by_verdict("Sell", "Overvalued") == ("Sell", "")
    assert gate_by_verdict("Strong Sell", "Undervalued")[0] == "Hold"
    assert gate_by_verdict("Buy", "Undervalued") == ("Buy", "")
    assert gate_by_verdict("Buy", "Fairly valued") == ("Buy", "")


def test_segment_with_unverified_quote_keeps_only_its_name_and_comparables():
    src = "Our Mobility segment connects riders and drivers. Delivery revenue was $17,248 million."
    data = {"segments": [
        {"name": "Mobility", "revenue_millions": 29670, "quote": "Mobility is our biggest business.",
         "comparable_us_tickers": ["LYFT"]},
        {"name": "Delivery", "revenue_millions": 17248, "quote": "Delivery revenue was $17,248 million.",
         "comparable_us_tickers": ["DASH"]}]}
    out, dropped = verify(data, src)
    assert [s["name"] for s in out["segments"]] == ["Delivery"]
    assert out["segments_unverified"] == [{"name": "Mobility", "comparable_us_tickers": ["LYFT"]}]  # no numbers
    assert any("Mobility" in d for d in dropped)


def test_quoted_table_row_matches_the_extracted_table():
    src = " | Mobility | | | $ | 25,087 | | | $ | 29,670 | | | | 18 | %\n\n | Delivery | | | 13,750 |"
    data = {"segments": [{"name": "Mobility", "revenue_millions": 29670, "quote": "Mobility $ 25,087 $ 29,670 18 %",
                          "comparable_us_tickers": ["LYFT"]}]}
    out, dropped = verify(data, src)
    assert [s["name"] for s in out["segments"]] == ["Mobility"] and not dropped
