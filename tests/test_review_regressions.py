"""Regression tests for the Phase 3 independent review: debt aggregation, leap-day LTM, LTM periods,
FMP quarter validation, missing-data flags."""
from datetime import date

import pytest

from data_desk import checks
from data_desk.fmp_statements import ltm_from_quarters
from data_desk.standardise import AMBIGUOUS_DEBT, standardise
from data_desk.xbrl import extract
from engine.dates import years_earlier
from tests.conftest import historicals_for, load_edgar_fixture
from tests.test_xbrl import fact, facts

# Total debt (US$m, excl. operating leases) per fixture. AAPL and KO match FMP's totals exactly once leases are
# added; CVX FY2024 equals short-term debt 4,406 + long-term debt 20,135 on the balance sheet; TRV and MU use the
# filer's own all-in total; O sums notes, loans, secured debt and commercial paper; GRAB is IFRS borrowings.
GOLDEN_DEBT = {
    ("AAPL", "FY2025"): 98_657, ("KO", "FY2025"): 45_492, ("UBER", "FY2025"): 10_521,
    ("UBER", "LTM 2026-06-30"): 12_723, ("GRAB", "FY2025"): 2_053, ("MU", "FY2025"): 14_577,
    ("TRV", "FY2025"): 9_267, ("O", "FY2025"): 27_288, ("CVX", "FY2024"): 24_541,
}


@pytest.mark.parametrize("ticker,period", list(GOLDEN_DEBT))
def test_golden_total_debt(ticker, period):
    h = historicals_for(ticker)
    assert h.v("total_debt", period) == pytest.approx(GOLDEN_DEBT[(ticker, period)], rel=0.001), \
        "\n".join(h.get("total_debt", period).trace())


def test_finance_leases_not_double_counted_when_in_debt_tag():
    h = historicals_for("MU")  # DebtAndCapitalLeaseObligations already includes 3,044 of finance leases
    lease = h.get("lease_liabilities", "FY2025")
    assert lease.value == pytest.approx(h.v("operating_lease_liabilities", "FY2025"))
    assert h.v("total_debt_incl_leases", "FY2025") == pytest.approx(14_577 + lease.value)


def test_cvx_ambiguous_debt_tags_flagged():
    h = historicals_for("CVX")
    assert AMBIGUOUS_DEBT in h.get("total_debt", "FY2024").note
    assert checks.ambiguous_debt(h, ["FY2024"], AMBIGUOUS_DEBT)[0].code == "debt_tags_ambiguous"


def test_cash_falls_back_to_cash_flow_ending_cash():
    h = historicals_for("CVX")  # CVX stopped tagging balance-sheet cash
    v = h.get("cash", "FY2025")
    assert v.value is not None and "cash-flow ending cash" in v.note
    assert h.v("net_debt", "FY2025") is not None


def test_missing_key_lines_flagged():
    h = historicals_for("UBER")
    del h.lines["cash"]["FY2025"]
    f = checks.missing_key_lines(h, ["FY2025"])
    assert f and "cash" in f[0].numbers["missing"]


def test_leap_day_quarter_end_does_not_crash():
    assert years_earlier(date(2024, 2, 29)) == date(2023, 2, 28)
    cf = facts(Revenues=[
        fact(100e6, "2022-09-01", "2021-09-03"), fact(120e6, "2023-08-31", "2022-09-02", filed="2023-10-01"),
        fact(50e6, "2023-03-02", "2022-09-02", form="10-Q"),
        fact(70e6, "2024-02-29", "2023-09-01", form="10-Q", filed="2024-03-30")])
    h = extract(cf)
    assert h.v("revenue", "LTM 2024-02-29") == 120 + 70 - 50


def test_aapl_ltm_matches_sum_of_quarters():
    """Independent path: LTM from three-month quarterly facts, not the year-to-date facts the extractor uses."""
    d = load_edgar_fixture("AAPL")
    rows = d["companyfacts"]["facts"]["us-gaap"]["RevenueFromContractWithCustomerExcludingAssessedTax"]["units"]["USD"]
    h = historicals_for("AAPL")
    ltm_end = h.ltm.end.isoformat()

    def quarter(end):
        q = [r for r in rows if r["end"] == end and r.get("start") and
             80 <= (date.fromisoformat(r["end"]) - date.fromisoformat(r["start"])).days <= 100]
        return max(q, key=lambda r: r["filed"])["val"] / 1e6

    quarter_ends = sorted({r["end"] for r in rows if r.get("form") == "10-Q" and r["end"] > "2025-09-27"})
    assert quarter_ends[-1] == ltm_end and len(quarter_ends) == 3
    prior_ends = sorted({r["end"] for r in rows if r.get("form") == "10-Q" and "2024-09-28" < r["end"] < "2025-09-27"})
    fy = h.v("revenue", "FY2025")
    q4_fy25 = fy - sum(quarter(e) for e in prior_ends)
    assert h.v("revenue", h.ltm.label) == pytest.approx(q4_fy25 + sum(quarter(e) for e in quarter_ends), rel=1e-9)


def _q(d, **f):
    return {"date": d, **f}


def test_fmp_ltm_requires_consecutive_quarters():
    inc = [_q(d, revenue=100.0e6) for d in ("2026-06-30", "2026-03-31", "2025-12-31", "2025-09-30")]
    cash = [_q(d, operatingCashFlow=10.0e6) for d in ("2026-06-30", "2026-03-31", "2025-12-31", "2025-09-30")]
    period, vals = ltm_from_quarters(inc, cash, [], date(2025, 12, 31), "USD", None)
    assert period.source == "FMP" and vals["revenue"].value == 400 and vals["cfo"].value == 40
    gap = inc[:3] + [_q("2025-06-30", revenue=100.0e6)]  # a quarter missing: would sum ~15 months
    assert ltm_from_quarters(gap, cash, [], date(2025, 12, 31), "USD", None) == (None, {})
    mismatched = cash[:3] + [_q("2025-06-30", operatingCashFlow=10.0e6)]
    _, vals = ltm_from_quarters(inc, mismatched, [], date(2025, 12, 31), "USD", None)
    assert "cfo" not in vals and "revenue" in vals


def test_ltm_from_fmp_does_not_add_leases_again():
    h = historicals_for("GRAB")
    from engine.model import Period
    from engine.values import Value
    p = Period("LTM 2026-06-30", date(2026, 6, 30), None, "LTM", source="FMP")
    h.periods.append(p)
    h.lines["debt_current"][p.label] = Value(1700.0, "USD", "m", p.label, "FMP")
    h.lines["long_term_debt"][p.label] = Value(500.0, "USD", "m", p.label, "FMP")
    h = standardise(h)
    assert h.v("total_debt_incl_leases", p.label) == pytest.approx(2200.0)
