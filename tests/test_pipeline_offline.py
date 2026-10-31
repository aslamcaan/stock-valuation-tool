"""A whole report, offline: every desk runs, including the code paths that only open up when the AI desks return
data (segments for the sum of the parts, one-off items, KPIs). The MSFT crash (SOTP summing (name, amount) pairs)
lived on such a path, which the unit tests never reached.

SEC data comes from the recorded KO fixture, market data from a small stub, engine inputs from the recorded KO
inputs, and the AI from a fake that returns schema-valid answers (research answers carry real content).
"""
from __future__ import annotations

from datetime import date

import pytest

import datasources.damodaran as dam
from core.config import Settings
from core.http import cache_key
from core.services import build_services
from data_desk.filings import FilingText
from datasources.edgar import COMPANYFACTS_URL, SUBMISSIONS_URL, TICKERS_URL
from datasources.market import MarketData, MarketResult
from desks.ai import AIClient, CostLedger
from engine.comps import CompanyMetrics
from tests.conftest import FIXTURES, load_edgar_fixture
from tests.engine_fixtures import engine_inputs

TODAY = date(2026, 10, 15)
FILING = ("Item 7. Management's Discussion and Analysis. The Company operates two segments. Concentrate operations "
          "revenue was $30,000 million and operating income $12,000 million in 2025. Bottling investments revenue was "
          "$18,000 million and operating income $1,800 million in 2025. "
          "During 2025 the Company recorded an impairment of the BodyArmor trademark of $960 million. "
          "During 2024 the Company recorded a remeasurement of the fairlife contingent consideration of $3,109 "
          "million. Unit case volume grew 2% in 2025.")
RESEARCH = {
    "segments": [
        {"name": "Concentrate operations", "description": "", "revenue_millions": 30000, "profit_millions": 12000,
         "profit_metric": "Operating income", "fiscal_year": "2025", "comparable_us_tickers": ["PEP", "KDP"],
         "quote": "Concentrate operations revenue was $30,000 million and operating income $12,000 million in 2025."},
        {"name": "Bottling investments", "description": "", "revenue_millions": 18000, "profit_millions": 1800,
         "profit_metric": "Operating income", "fiscal_year": "2025", "comparable_us_tickers": ["COKE"],
         "quote": "Bottling investments revenue was $18,000 million and operating income $1,800 million in 2025."}],
    "one_off_items": [
        {"description": "BodyArmor impairment", "amount_millions": 960, "fiscal_year": "2025", "effect": "charge",
         "in_operating_income": True,
         "quote": "During 2025 the Company recorded an impairment of the BodyArmor trademark of $960 million."},
        {"description": "fairlife remeasurement", "amount_millions": 3109, "fiscal_year": "2024", "effect": "charge",
         "in_operating_income": True,
         "quote": "During 2024 the Company recorded a remeasurement of the fairlife contingent consideration of "
                  "$3,109 million."}],
    "kpis": [{"name": "Unit case volume growth", "value_text": "2%", "period": "2025",
              "quote": "Unit case volume grew 2% in 2025."}],
}


def instance(schema: dict):
    """The smallest JSON value valid against `schema` (numbers 3: inside every 1-5 score range used)."""
    if "enum" in schema:
        return schema["enum"][0]
    t = schema.get("type")
    t = t[0] if isinstance(t, list) else t
    if t == "object":
        return {k: instance(v) for k, v in schema.get("properties", {}).items()}
    if t == "array":
        return [instance(schema["items"])] * schema.get("minItems", 0)
    return {"string": "", "number": 3, "integer": 3, "boolean": False, "null": None}.get(t)


class FakeAI(AIClient):
    """Answers every desk without the network; the research desk's answers carry RESEARCH where its schema asks."""

    def __init__(self, cache, ledger):
        super().__init__("test-key", cache, ledger)
        self.desks: list[str] = []

    def call(self, *, report_id, desk, schema, with_sources=False, **_):
        self.desks.append(desk)
        out = instance(schema)
        if desk == "Research desk":
            out.update({k: v for k, v in RESEARCH.items() if k in out})
        return {"data": out, "sources": [], "searched_at": TODAY.isoformat()} if with_sources else out


class StubMarket(MarketData):
    """KO's price and market cap; every other market call answers 'no data' (the report must degrade, not crash)."""

    def __getattribute__(self, name):
        if name in ("quote", "market_cap"):
            return object.__getattribute__(self, "_" + name)
        if not name.startswith("_") and callable(getattr(MarketData, name, None)):
            return lambda *a, **k: [] if name == "coverage" else MarketResult(None, None, None, False, ["stub"])
        return object.__getattribute__(self, name)

    def _quote(self, symbol):
        return MarketResult({"price": 94.08, "as_of": TODAY.isoformat()}, "Stub", TODAY.isoformat())

    def _market_cap(self, symbol):
        return MarketResult({"market_cap": 94.08 * 4_313.5e6, "currency": "USD", "as_of": TODAY.isoformat(),
                             "listing": symbol}, "Stub", TODAY.isoformat())


class BrokeAI(FakeAI):
    """Every call fails the way an exhausted Anthropic account does."""

    def call(self, *, report_id, desk, **_):
        from desks.ai import AIError
        self.desks.append(desk)
        raise AIError(f"{desk}: the Anthropic account is out of credit (top up under Plans & Billing); AI desks skipped")


@pytest.fixture(scope="module")
def report(tmp_path_factory):
    yield from _run(tmp_path_factory, FakeAI)


@pytest.fixture(scope="module")
def broke_report(tmp_path_factory):
    yield from _run(tmp_path_factory, BrokeAI)


def _run(tmp_path_factory, ai_class):
    import desks.modelling as modelling
    import desks.pipeline as pipeline
    mp = pytest.MonkeyPatch()
    root = tmp_path_factory.mktemp("cache")
    svc = build_services(Settings(sec_user_name="Test", sec_user_email="t@example.com", cache_dir=root,
                                  offline=True, anthropic_api_key="test-key"))
    d = load_edgar_fixture("KO")
    svc.cache.write("companyfacts", cache_key(COMPANYFACTS_URL.format(cik=d["cik"])), d["companyfacts"])
    svc.cache.write("filings", cache_key(SUBMISSIONS_URL.format(cik=d["cik"])), d["submissions"])
    svc.cache.write("reference", cache_key(TICKERS_URL), [d["tickers_row"]] + [
        {"cik_str": 1000 + i, "ticker": t, "title": t} for i, t in enumerate(("PEP", "KDP", "COKE"))])
    for name, fname in (("erp", "ERPbymonth.xlsx"), ("country", "ctryprem.xlsx"), ("betas_us", "betas.xls"),
                        ("margins_us", "margin.xls")):
        svc.cache.write("damodaran", cache_key(dam.BASE + dam.FILES[name]),
                        (FIXTURES / "damodaran" / fname).read_bytes(), binary=True)
    svc.market = StubMarket(svc.fmp, svc.tiingo, svc.finnhub)
    svc.ai = ai_class(svc.cache, CostLedger(svc.db, 1.0, 5.0))

    filing = FilingText("10-K", "2026-02-20", "2025-12-31", "https://www.sec.gov/test", {"mdna": FILING})
    mp.setattr(pipeline, "latest_annual_report", lambda svc, cik, years_back=0: filing)
    mp.setattr(pipeline, "gather_peers", lambda svc, ticker, progress=None: ([], []))
    mp.setattr(modelling, "build_engine_inputs", lambda cd, svc, today=None, overrides=None: (
        engine_inputs("KO", overrides), []))

    def peer(svc, ticker, rows):  # each segment comparable trades at a known EV/Sales
        return CompanyMetrics(ticker, ticker, "2080", 100_000.0, 50.0, 20_000.0 if ticker != "COKE" else 50_000.0,
                              4_000.0, 2_000.0, 1_500.0, None, 10_000.0, 2_000.0), None
    mp.setattr(modelling, "peer_metrics", peer)
    rep = pipeline.run_report("KO", svc, valuation_date=TODAY)
    yield rep, svc
    mp.undo()


def test_every_desk_runs_to_the_end(report):
    rep, svc = report
    assert rep.stopped is None, rep.stopped
    assert rep.model is not None and rep.md is not None
    assert {"Research desk", "Review desk", "MD"} <= set(svc.ai.desks)


def test_research_data_reaches_the_valuation(report):
    rep, _ = report
    v = rep.model.valuation
    assert v.sotp.applicable  # the MSFT path: segments valued through the engine
    assert [name for name, _, _ in v.sotp.segment_values] == ["Concentrate operations", "Bottling investments"]
    assert rep.model.inputs.one_off_adjustments == {"FY2025": 960.0, "FY2024": 3109.0}
    assert v.reverse["wacc"]["solved"] and v.reverse.get("street")


def test_the_report_saves_and_reloads(report):
    from desks.pipeline import load
    rep, svc = report
    again = load(rep.report_id, svc.store)
    assert again.model.verdict.fair_value == pytest.approx(rep.model.verdict.fair_value)


def test_a_report_without_ai_credit_still_values_the_company(broke_report):
    """JPM, 2026-10-31: an out-of-credit API error escaped the pipeline and the whole report failed."""
    rep, svc = broke_report
    assert rep.model is not None and rep.model.verdict.fair_value is not None
    assert rep.md is None and rep.desk_status["MD"][0] == "failed"
    assert "out of credit" in rep.desk_status["MD"][1]


def test_api_errors_become_readable_ai_errors(tmp_path):
    from core.cache import Cache
    from core.db import Database
    from desks.ai import AIError

    class BadRequestError(Exception):  # stands in for anthropic.BadRequestError (same module, status and message)
        status_code = 400
    BadRequestError.__module__ = "anthropic._exceptions"

    class Refusing:
        class messages:
            @staticmethod
            def create(**_):
                raise BadRequestError("Your credit balance is too low to access the Anthropic API.")

    ai = AIClient("test-key", Cache(tmp_path / "c"), CostLedger(Database(tmp_path / "t.sqlite"), 1.0, 5.0),
                  client=Refusing())
    with pytest.raises(AIError, match="out of credit"):
        ai.call(report_id="r", desk="MD", model="claude-haiku-5-5", system="s", content="c",
                schema={"type": "object", "properties": {}})

    class Other(Exception):  # an error from our own code is not dressed up as an API failure
        pass
    Refusing.messages.create = staticmethod(lambda **_: (_ for _ in ()).throw(Other("bug")))
    with pytest.raises(Other):
        ai.call(report_id="r", desk="MD", model="claude-haiku-5-5", system="s", content="d",
                schema={"type": "object", "properties": {}})


def test_what_changed_between_versions_names_the_drivers():
    from ui.report import what_changed
    old = {"components": {"dcf": 62.72, "comps": 19.05, "history": 80.0}, "wacc": 0.083, "growth": 0.15,
           "margin": 0.12, "stage": "High growth", "price": 71.27}
    new = {"components": {"dcf": 65.89, "comps": 61.57, "history": 80.5}, "wacc": 0.081, "growth": 0.152,
           "margin": 0.12, "stage": "High growth", "price": 65.25}
    assert what_changed(old, new) == ["DCF $62.72 → $65.89", "peer multiples $19.05 → $61.57", "WACC 8.3% → 8.1%",
                                      "price $71.27 → $65.25"]
    assert what_changed(old, old) == []
