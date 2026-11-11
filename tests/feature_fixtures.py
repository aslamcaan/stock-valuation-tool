"""A report-shaped object built from the recorded KO inputs, for the feature tests (no network, no AI)."""
import copy
from types import SimpleNamespace

from engine.valuation import value_company
from tests.engine_fixtures import engine_inputs


def fake_report(ticker: str = "KO", price_factor: float | None = None):
    i = copy.deepcopy(engine_inputs(ticker))
    v = value_company(i)
    price = i.price.value if price_factor is None else v.dcf_figures["base"] * price_factor
    verdict = SimpleNamespace(price=price, fair_value=v.dcf_figures["probability_weighted"], verdict="Fairly valued",
                              confidence="Medium", gap=0.0, weights_used={"dcf": 1.0}, components={"dcf": 1.0})
    model = SimpleNamespace(valuation=v, verdict=verdict, financial=None, inputs=i, comps=None, flags=[])
    company = SimpleNamespace(analysis=i.analysis, historicals_usd=i.historicals,
                              profile=SimpleNamespace(name="Test Co", ticker=ticker))
    return SimpleNamespace(ticker=ticker, model=model, company=company, peers_pool=[], report_id=f"fake-{ticker}",
                           created_at="2026-11-09T10:00:00+00:00", md=None)
