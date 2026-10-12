"""Golden fixtures are complete and internally consistent."""
import json

import pytest

from tests.conftest import FIXTURES


@pytest.fixture(scope="module")
def grab():
    return json.loads((FIXTURES / "grab_expected.json").read_text(encoding="utf-8"))


def test_grab_fixture_matches_workbook(grab):
    """Re-extracting the workbook gives the same fixture (no hand edits drifted)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("x", FIXTURES.parent.parent / "scripts" / "extract_grab_model.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert json.loads(json.dumps(mod.extract())) == grab


def test_grab_fixture_reproduces_value_per_share(grab):
    """The recorded conventions + assumptions reproduce the model's value per share exactly."""
    a, h, years = grab["assumptions"], grab["historicals"], grab["conventions"]["forecast_years"]
    rev, ufcf = h["FY2025A"]["revenue"]["value"], []
    for y in years:
        rev *= 1 + a["revenue_growth"][y]["value"]
        da = rev * a["d_and_a_pct_revenue"][y]["value"]
        ebit = rev * a["ebitda_margin"][y]["value"] - da
        ufcf.append(ebit * (1 - a["tax_rate"][y]["value"]) + da - rev * a["capex_pct_revenue"][y]["value"])
    for y, f in zip(years, ufcf):
        assert f == pytest.approx(grab["computed"]["ufcf"][y]["value"], rel=1e-12)
    bs = h["balance_sheet"]
    e = h["market"]["share_price"]["value"] * bs["shares_outstanding_m"]["value"]
    d = bs["total_debt"]["value"]
    ke = a["risk_free_rate"]["value"] + a["beta"]["value"] * a["equity_risk_premium"]["value"]
    w = (e * ke + d * a["pre_tax_cost_of_debt"]["value"] * (1 - a["debt_tax_rate"]["value"])) / (e + d)
    g = a["terminal_growth"]["value"]
    ev = sum(f / (1 + w) ** p for f, p in zip(ufcf, grab["conventions"]["discount_periods"]))
    ev += ufcf[-1] * (1 + g) / (w - g) / (1 + w) ** 5
    vps = (ev + bs["cash_and_investments"]["value"] - d) / bs["shares_outstanding_m"]["value"]
    assert vps == pytest.approx(grab["computed"]["value_per_share"]["value"], rel=1e-12)


def test_grab_every_value_has_a_cell(grab):
    def walk(node):
        if isinstance(node, dict):
            if "value" in node:
                assert node["cell"].startswith("'GRAB DCF'!")
            else:
                for v in node.values():
                    walk(v)
    walk(grab["historicals"]), walk(grab["assumptions"]), walk(grab["computed"])


def test_uber_fixture_complete():
    u = json.loads((FIXTURES / "uber_expected.json").read_text(encoding="utf-8"))
    assert set(u["metrics"]) == {"gross_bookings", "revenue", "operating_income", "net_income_attributable",
                                 "cash_from_operations", "capex", "total_assets", "total_equity", "long_term_debt"}
    assert u["metrics"]["operating_income"]["values"]["FY2023"] == 1110
    assert u["metrics"]["long_term_debt"]["values"]["FY2025"] == 10521
