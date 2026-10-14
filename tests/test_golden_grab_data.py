"""Golden test 1a (test_grab_data): historical inputs in the user's Grab model vs Grab's 20-F.

Revenue and share count must match within 0.5%. The model takes D&A and capex as 3% of revenue and
debt / cash from S&P definitions; those are recorded as known differences (agreed at Checkpoint 2).
Each comparison prints both values and the filing source, as the brief requires (run with -s to see).
"""
import json

import pytest

from tests.conftest import FIXTURES, historicals_for

MODEL = json.loads((FIXTURES / "grab_expected.json").read_text(encoding="utf-8"))
TOL = 0.005

# item -> (model section, model key, EDGAR line, reason, EDGAR FY2025 value)
KNOWN_DIFFERENCES = {
    "d_and_a": ("FY2025A", "d_and_a", "d_and_a", "model uses 3% of revenue; 20-F reports 177", 177.0),
    "capex": ("FY2025A", "capex", "capex", "model uses 3% of revenue; 20-F PP&E purchases are 97", 97.0),
    "total_debt": ("balance_sheet", "total_debt", "total_debt",
                   "model uses S&P total debt (1,600); 20-F borrowings are 2,053", 2053.0),
    "cash_and_investments": ("balance_sheet", "cash_and_investments", "cash_and_investments",
                             "model uses S&P cash + investments (6,861); 20-F cash 3,433 + current investments 3,371",
                             6804.0),
}


@pytest.fixture(scope="module")
def h():
    return historicals_for("GRAB")


def _report(name, model, v):
    print(f"{name}: model {model:,.1f} vs 20-F {v.value:,.1f} ({v.tag or v.formula}; {v.filing or 'calculated'})")


def test_grab_data_revenue(h):
    v = h.get("revenue", "FY2025")
    model = MODEL["historicals"]["FY2025A"]["revenue"]["value"]
    _report("revenue", model, v)
    assert v.value == pytest.approx(model, rel=TOL)


def test_grab_data_shares(h):
    v = h.get("shares_basic_weighted", "FY2025")
    model = MODEL["historicals"]["balance_sheet"]["shares_outstanding_m"]["value"]
    _report("shares (basic weighted)", model, v)
    assert v.value == pytest.approx(model, rel=TOL)


@pytest.mark.parametrize("item", list(KNOWN_DIFFERENCES))
def test_grab_data_known_differences(h, item):
    section, key, line, reason, edgar_expected = KNOWN_DIFFERENCES[item]
    model = MODEL["historicals"][section][key]["value"]
    v = h.get(line, "FY2025")
    _report(item, model, v)
    print(f"  known difference: {reason}")
    assert v.value == pytest.approx(edgar_expected, rel=TOL), "EDGAR extraction changed"
    assert abs(v.value / model - 1) > TOL, "now matches the model: remove from KNOWN_DIFFERENCES"


def test_grab_leases_and_sbc(h):
    assert h.v("lease_liabilities", "FY2025") == pytest.approx(234.0)
    assert h.v("sbc", "FY2025") == pytest.approx(241.0)
    assert h.taxonomy == "ifrs-full" and h.currency == "USD"
