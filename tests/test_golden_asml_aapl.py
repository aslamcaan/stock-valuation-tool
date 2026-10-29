"""Golden tests 3 and 4: ASML (EUR reporter, USD listing) FX conversion; AAPL September year end."""
import json
from datetime import date
from statistics import mean

import pytest

from data_desk import checks
from data_desk.fx import FxRates, FxSeries, to_usd
from tests.conftest import FIXTURES, historicals_for


@pytest.fixture(scope="module")
def fx():
    d = json.loads((FIXTURES / "fred_DEXUSEU.json").read_text(encoding="utf-8"))
    return FxRates({"EUR": FxSeries("EUR", d["series_id"], True, tuple(map(tuple, d["observations"])),
                                    d["fetched_at"])})


@pytest.fixture(scope="module")
def asml():
    return historicals_for("ASML")


def test_asml_reports_in_eur(asml):
    assert asml.currency == "EUR"
    assert checks.currency_mismatch(asml.currency)[0].code == "currency_mismatch"


def test_asml_income_statement_uses_period_average(asml, fx):
    usd, problems = to_usd(asml, fx)
    assert not problems
    obs = json.loads((FIXTURES / "fred_DEXUSEU.json").read_text(encoding="utf-8"))["observations"]
    avg_2025 = mean(v for d, v in obs if v and "2025-01-01" <= d <= "2025-12-31")
    rev = usd.get("revenue", "FY2025")
    assert rev.currency == "USD"
    assert rev.value == pytest.approx(asml.v("revenue", "FY2025") * avg_2025, rel=1e-12)
    assert "period-average" in rev.formula
    cfo = usd.get("cfo", "FY2025")
    assert cfo.value == pytest.approx(asml.v("cfo", "FY2025") * avg_2025, rel=1e-12)


def test_asml_balance_sheet_uses_period_end(asml, fx):
    usd, _ = to_usd(asml, fx)
    obs = json.loads((FIXTURES / "fred_DEXUSEU.json").read_text(encoding="utf-8"))["observations"]
    end_rate = [v for d, v in obs if v and d <= "2025-12-31"][-1]
    ta = usd.get("total_assets", "FY2025")
    assert ta.value == pytest.approx(asml.v("total_assets", "FY2025") * end_rate, rel=1e-12)
    assert "period-end" in ta.formula
    # derived balance-sheet aggregates also use the period-end rate
    nd = usd.get("net_debt", "FY2025")
    assert nd.value == pytest.approx(asml.v("net_debt", "FY2025") * end_rate, rel=1e-12)


def test_asml_rates_are_traceable(asml, fx):
    usd, _ = to_usd(asml, fx)
    trace = "\n".join(usd.get("revenue", "FY2025").trace())
    assert "FRED DEXUSEU" in trace and "us-gaap:" in trace


def test_missing_fx_rate_reported(asml):
    empty = FxRates({"EUR": FxSeries("EUR", "DEXUSEU", True, (("2001-01-02", 0.9),))})
    usd, problems = to_usd(asml, empty)
    assert usd is None and problems


@pytest.fixture(scope="module")
def aapl():
    return historicals_for("AAPL")


def test_aapl_september_year_end(aapl):
    fy25 = next(p for p in aapl.periods if p.label == "FY2025")
    assert fy25.end == date(2025, 9, 27)
    assert aapl.v("revenue", "FY2025") == pytest.approx(416_161, rel=0.005)
    assert aapl.v("revenue", "FY2024") == pytest.approx(391_035, rel=0.005)
    assert aapl.ltm is not None and aapl.ltm.end > fy25.end
    assert aapl.ltm.ytd_start == date(2025, 9, 28)


def test_aapl_ltm_uses_matching_ytd_periods(aapl):
    """The YTD inputs must be the nine months to the LTM date and the same nine months a year earlier."""
    v = aapl.get("revenue", aapl.ltm.label)
    fy, cur, prior = v.inputs
    assert fy.period == "FY2025"
    assert cur.period == f"YTD to {aapl.ltm.end}" and prior.period == "YTD to 2025-06-27"
    assert aapl.ltm.ytd_months == 9


def test_aapl_debt_includes_commercial_paper(aapl):
    assert aapl.v("total_debt_incl_leases", "FY2025") == pytest.approx(112_377, rel=0.005)


def test_every_balance_sheet_derived_line_uses_the_period_end_rate():
    """Debt for valuation is a balance-sheet amount: converting it at the average rate mis-states it by the FX move."""
    from data_desk import fx
    from data_desk.standardise import DERIVED_LABELS
    instant = {"total_debt", "lease_liabilities", "total_debt_incl_leases", "debt_for_valuation",
               "cash_and_investments", "net_debt"}
    assert {l for l in DERIVED_LABELS if fx._is_instant(l)} == instant
