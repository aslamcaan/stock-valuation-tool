"""Golden test 2: Uber historicals (US$m, FY2023-FY2025) and the net-income flag."""
import json

import pytest

from data_desk import checks
from tests.conftest import FIXTURES, historicals_for

EXPECTED = json.loads((FIXTURES / "uber_expected.json").read_text(encoding="utf-8"))
LINE_FOR = {"revenue": "revenue", "operating_income": "operating_income",
            "net_income_attributable": "net_income_attributable", "cash_from_operations": "cfo", "capex": "capex",
            "total_assets": "total_assets", "total_equity": "total_equity", "long_term_debt": "long_term_debt"}


@pytest.fixture(scope="module")
def h():
    return historicals_for("UBER")


@pytest.mark.parametrize("metric", list(LINE_FOR))
def test_uber_historicals_match(h, metric):
    for fy, expected in EXPECTED["metrics"][metric]["values"].items():
        v = h.get(LINE_FOR[metric], fy)
        assert v is not None and v.value is not None, f"{metric} {fy} missing"
        assert v.value == pytest.approx(expected, rel=EXPECTED["tolerance"]), \
            f"{metric} {fy}: EDGAR {v.value:,.0f} ({v.tag}, {v.filing}) vs expected {expected:,.0f}"


def test_uber_net_income_flag(h):
    flagged = {f.period for f in checks.net_income_vs_operating(h)}
    assert {"FY2024", "FY2025"} <= flagged
    assert "FY2023" not in flagged


def test_uber_gross_bookings_kpi_check(h):
    gb = EXPECTED["metrics"]["gross_bookings"]["values"]
    # revenue and gross bookings grew within 5 points of each other in FY2024 and FY2025
    assert checks.kpi_divergence(h, "gross bookings", gb) == []
    shifted = {**gb, "FY2025": gb["FY2024"] * 1.30}
    assert [f.period for f in checks.kpi_divergence(h, "gross bookings", shifted)] == ["FY2025"]
