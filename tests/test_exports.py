"""Excel export (formulas recalculate to the engine's numbers, no errors) and PDF export, offline."""
from datetime import date
from types import SimpleNamespace

import pytest

from engine.verdict import blend
from engine.valuation import value_company
from exports.excel import build_workbook
from exports.pdf import build_pdf
from exports.verify import verify
from tests.engine_fixtures import engine_inputs


@pytest.fixture(scope="module")
def rep():
    ei = engine_inputs("GRAB")
    v = value_company(ei)
    dcf_value = v.per_us_share(v.scenario_value)
    verdict = blend({"dcf": dcf_value, "comps": None, "history": None}, ei.price.value)
    verdict.confidence, verdict.confidence_reasons = "Low", ["test"]
    model = SimpleNamespace(valuation=v, inputs=ei, comps=None, history={}, verdict=verdict, assumptions=[],
                            sources=[], flags=[], football=[], analyst_targets=None, company_metrics=None,
                            revisions={}, trace={})
    profile = SimpleNamespace(name="Grab Holdings", ticker="GRAB", exchange="Nasdaq", sic_description="Services",
                              reporting_currency="USD")
    company = SimpleNamespace(profile=profile, historicals=ei.historicals, analysis=ei.analysis)
    return SimpleNamespace(model=model, company=company, md=None, review=None, research=None, ticker="GRAB",
                           report_id="GRAB-test", created_at="2026-10-15T00:00:00", valuation_date=date(2026, 10, 15))


def test_excel_formulas_match_engine(rep, tmp_path):
    path = tmp_path / "grab.xlsx"
    wb = build_workbook(rep)
    assert {"Cover", "Inputs", "Historicals", "Ratios", "Forecast", "WACC", "DCF", "Comps", "Scenarios",
            "Sensitivity", "Summary"} <= set(wb.sheetnames)
    wb.save(path)
    r = verify(path)
    assert r["errors"] == [] and r["formulas"] > 1000
    assert r["dcf_check"] == pytest.approx(0, abs=1e-9)
    assert r["fair_value_check"] == pytest.approx(0, abs=1e-9)
    assert r["verdict"] == rep.model.verdict.verdict


def test_excel_banking_conventions(rep):
    wb = build_workbook(rep)
    inp, dcf = wb["Inputs"], wb["DCF"]
    assert not inp.sheet_view.showGridLines and inp.freeze_panes == "B5"
    price = next(c for row in inp.iter_rows() for c in row if c.value == rep.model.inputs.price.value)
    assert price.font.color.rgb.endswith("0000FF")                      # blue input
    links = [c for row in dcf.iter_rows() for c in row if isinstance(c.value, str) and "Inputs" in c.value]
    assert links and all(c.font.color.rgb.endswith("008000") for c in links)  # green cross-sheet links
    assert wb["Summary"]["B15"].font.color.rgb.endswith("C00000")        # red check row
    assert "US$" in wb["DCF"]["A2"].value                                 # units label


def test_pdf_builds(rep):
    pdf = build_pdf(rep)
    assert pdf[:4] == b"%PDF" and len(pdf) > 5000
