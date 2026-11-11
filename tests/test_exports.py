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


def test_excel_stores_every_formula_result(rep):
    """Protected View, previews and phone viewers show stored results only: the DCF, WACC and Summary sheets were
    blank before results were stored. Every formula keeps its formula and now carries its value."""
    from io import BytesIO
    from openpyxl import load_workbook
    from exports.excel import export_bytes
    b = export_bytes(rep)
    wf, wv = load_workbook(BytesIO(b)), load_workbook(BytesIO(b), data_only=True)
    formulas = [(ws.title, c.coordinate) for ws in wf.worksheets for row in ws.iter_rows() for c in row
                if isinstance(c.value, str) and c.value.startswith("=")]
    assert len(formulas) > 1000  # still live formulas
    blank = [(t, ref) for t, ref in formulas if wv[t][ref].value is None and wf[t][ref].value != '=""'
             and "\"\")" not in wf[t][ref].value and ',"")' not in wf[t][ref].value]
    assert blank == []
    assert wv["DCF"]["B35"].value == pytest.approx(rep.model.valuation.dcf.value_per_share)
    assert wv["Summary"]["B12"].value == rep.model.verdict.verdict


def test_excel_sotp_sheet_shows_the_working_and_matches_the_engine(tmp_path):
    from pycel import ExcelCompiler
    from engine.sotp import Segment
    ei = engine_inputs("GRAB")
    ei.segments = [Segment("Deliveries", 1800, 300, metric="EV/EBIT", metric_value=300, multiple=18.0,
                           multiple_source="median EV/EBIT of DASH 30.0x, UBER 18.0x"),
                   Segment("Mobility", 1100, 40, metric="EV/EBIT", metric_value=40, multiple=12.0,
                           multiple_source="median EV/EBIT of LYFT 12.0x"),
                   Segment("Corporate and unallocated costs", 0.0, -60, metric="EV/EBIT", metric_value=-60,
                           multiple=(300 * 18 + 40 * 12) / 340, multiple_source="capitalised")]
    v = value_company(ei)
    assert v.sotp.applicable
    verdict = blend({"dcf": v.per_us_share(v.scenario_value), "comps": None, "history": None}, ei.price.value,
                    sotp=v.per_us_share(v.sotp.value_per_share))
    model = SimpleNamespace(valuation=v, inputs=ei, comps=None, history={}, verdict=verdict, assumptions=[],
                            sources=[], flags=[], football=[], analyst_targets=None, company_metrics=None,
                            revisions={}, trace={})
    profile = SimpleNamespace(name="Grab", ticker="GRAB", exchange="Nasdaq", sic_description="", reporting_currency="USD")
    rep = SimpleNamespace(model=model, company=SimpleNamespace(profile=profile, historicals=ei.historicals,
                                                               analysis=ei.analysis),
                          md=None, review=None, research=None, ticker="GRAB", report_id="GRAB-sotp",
                          created_at="2026-10-15T00:00:00", valuation_date=date(2026, 10, 15))
    path = tmp_path / "sotp.xlsx"
    build_workbook(rep).save(path)
    xl = ExcelCompiler(filename=str(path), plugins=["exports.pycel_ext"])
    assert xl.evaluate("SOTP!E5") == pytest.approx(300 * 18.0)  # metric x multiple, as a formula
    assert xl.evaluate("SOTP!E8") == pytest.approx(v.sotp.enterprise_value)
    assert xl.evaluate("SOTP!E9") == pytest.approx(v.per_us_share(v.sotp.value_per_share))


def test_excel_analysis_tab_checks_to_zero(rep):
    """The Analysis tab (walk to the price, no-growth split, Monte Carlo) rebuilds what the app shows: its check rows
    are zero."""
    from io import BytesIO
    from openpyxl import load_workbook
    from exports.excel import export_bytes
    wb = load_workbook(BytesIO(export_bytes(rep)), data_only=True)
    an = wb["Analysis"]
    checks = [an[f"B{c.row}"].value for c in an["A"] if isinstance(c.value, str) and c.value.startswith("Check")]
    assert len(checks) >= 2 and all(x == pytest.approx(0, abs=1e-6) for x in checks)
    labels = [c.value for c in an["A"] if c.value]
    assert any(str(x).startswith("3. Monte Carlo") for x in labels)


def test_rsq_matches_engine_regression():
    from engine.insights import _ols
    from exports.pycel_ext import rsq
    xs, ys = (0.1, 0.2, 0.3, 0.4, 0.55), (2.0, 3.1, 3.9, 5.2, 6.0)
    assert rsq(ys, xs) == pytest.approx(_ols(list(xs), list(ys))[2])


def test_excel_headline_follows_the_apps_fallback_to_the_scenario_weighted_dcf(rep, tmp_path):
    """NVDA, 11 Nov: the app's headline was the scenario-weighted DCF ($189.77) but the workbook still blended the sum of
    the parts ($242.93), so its check cell read 53.17 and its verdict differed from the report's."""
    from dataclasses import replace
    v = rep.model.verdict
    fb = replace(v, weights_used={"dcf": 1.0}, fallback="divergence", dcf_value=v.fair_value)
    rep2 = SimpleNamespace(**{**rep.__dict__, "model": SimpleNamespace(**{**rep.model.__dict__, "verdict": fb})})
    path = tmp_path / "fb.xlsx"
    build_workbook(rep2).save(path)
    r = verify(path)
    assert r["errors"] == [] and r["fair_value_check"] == pytest.approx(0, abs=1e-9)
    assert r["verdict"] == fb.verdict
    assert build_workbook(rep2)["Summary"]["A10"].value.startswith("Fair value (scenario-weighted DCF")


def test_pdf_text_never_prints_a_missing_glyph_box_and_tables_are_tidy():
    from exports.pdf import assumption_value, clean, printable, stamp
    assert printable("non‑marketable") == "non-marketable"           # non-breaking hyphen (NVDA's filing quote)
    assert clean("a​b c d").replace(" ", " ") == "ab c d" and printable("café – “q”") == "café – “q”"
    assert "■" not in clean("x‑y \U0001f600 z") and "&amp;" in clean("AT&T")
    assert assumption_value({"value": 0.001718, "unit": "%"}) == "0.17%" and assumption_value({"value": 2.216, "unit": "x"}) == "2.22x"
    assert assumption_value({"value": "FY2026", "unit": None}) == "FY2026"
    assert stamp("2026-11-11T12:02:36.449137198-05:00") == "2026-11-11 12:02 UTC-05:00"
    assert stamp("2026-10-14T16:48:23+00:00") == "2026-10-14 16:48 UTC" and stamp("2026-11-11") == "2026-11-11"


def test_compare_pdf_survives_markup_characters_in_names():
    from exports.compare_pdf import build_compare_pdf
    from engine.compare_table import COLUMNS
    row = {"rank": 1, **{k: ("AT&T <b>" if kind == "text" else None) for k, _, kind in COLUMNS}}
    assert build_compare_pdf([row])[:4] == b"%PDF"


def test_excel_reconciles_to_the_app_and_carries_the_raw_bull_path_when_there_is_one(tmp_path):
    """The bull case runs on the analysts' raw growth path when the plan has one (MU, AMD, PLTR, 11 Nov: it ignored it and the
    check cell was off by up to $928 a share). Give the fixture a raw path and require the bull block to use it."""
    import copy
    ei = engine_inputs("GRAB")
    v = value_company(ei)
    v2 = copy.copy(v)
    v2.plan = copy.copy(v.plan)
    v2.plan.raw_growth_path = [g + 0.05 for g in v.plan.path("revenue_growth")]
    rep2 = rep_for(ei, v2)
    from dataclasses import replace as rp
    v2.scenarios = [rp(sc, scenario=rp(sc.scenario, raw_consensus_growth=True)) if sc.scenario.name == "Bull" else sc
                    for sc in v2.scenarios]
    wb = build_workbook(rep2)
    assert any("raw path" in str(c.value) for row in wb["Inputs"].iter_rows() for c in row)
    calc = wb["Calc"]
    bull_start = next(r for r in range(1, calc.max_row) if calc.cell(r, 1).value == "Bull scenario")
    assert "Inputs" in str(calc.cell(bull_start + 2, 2).value)        # the growth row of the bull block links to Inputs
    path = tmp_path / "raw.xlsx"
    wb.save(path)
    assert verify(path)["errors"] == []


def rep_for(ei, v):
    dcf_value = v.per_us_share(v.scenario_value)
    verdict = blend({"dcf": dcf_value, "comps": None, "history": None}, ei.price.value, dcf_value=dcf_value)
    model = SimpleNamespace(valuation=v, inputs=ei, comps=None, history={}, verdict=verdict, assumptions=[], sources=[],
                            flags=[], football=[], analyst_targets=None, company_metrics=None, revisions={}, trace={})
    profile = SimpleNamespace(name="Grab Holdings", ticker="GRAB", exchange="Nasdaq", sic_description="Services",
                              reporting_currency="USD")
    company = SimpleNamespace(profile=profile, historicals=ei.historicals, analysis=ei.analysis)
    return SimpleNamespace(model=model, company=company, md=None, review=None, research=None, ticker="GRAB",
                           report_id="GRAB-test", created_at="2026-10-15T00:00:00", valuation_date=date(2026, 10, 15))
