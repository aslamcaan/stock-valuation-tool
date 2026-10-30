"""XBRL extraction rules on small synthetic companyfacts."""
from datetime import date

from data_desk.standardise import standardise
from data_desk.xbrl import extract, fy_label


def fact(val, end, start=None, form="10-K", filed="2025-02-01", accn="a1"):
    r = {"val": val, "end": end, "form": form, "filed": filed, "accn": accn}
    if start:
        r["start"] = start
    return r


def facts(**tags):
    """tags: name -> list of facts. Suffix '_eur' for EUR units."""
    out = {"us-gaap": {}, "ifrs-full": {}}
    for name, rows in tags.items():
        unit = "EUR" if name.endswith("_eur") else "USD"
        out["us-gaap"][name.removesuffix("_eur")] = {"units": {unit: rows}}
    return {"facts": out}


def test_fy_label_rules():
    assert fy_label(date(2025, 9, 27)) == "FY2025"     # Apple, late September
    assert fy_label(date(2026, 1, 31)) == "FY2026"     # retailer year ending January
    assert fy_label(date(2026, 1, 3)) == "FY2025"      # 52/53-week year ending first week of January


def test_restated_value_wins_and_units_normalised():
    cf = facts(Revenues=[fact(100e6, "2024-12-31", "2024-01-01", filed="2025-02-01"),
                         fact(105e6, "2024-12-31", "2024-01-01", filed="2026-02-01", accn="a2"),  # restated
                         fact(120e6, "2025-12-31", "2025-01-01", filed="2026-02-01", accn="a2")])
    h = extract(cf)
    assert h.fy_labels == ["FY2024", "FY2025"]
    v = h.get("revenue", "FY2024")
    assert v.value == 105.0 and v.unit == "m" and v.tag == "us-gaap:Revenues" and "a2" in v.filing


def test_quarterly_facts_ignored_for_annual():
    cf = facts(Revenues=[fact(30e6, "2025-03-31", "2025-01-01", form="10-Q"),
                         fact(120e6, "2025-12-31", "2025-01-01")])
    assert extract(cf).v("revenue", "FY2025") == 120.0


def test_fallback_tag_logged():
    cf = facts(Revenues=[fact(120e6, "2025-12-31", "2025-01-01"), fact(110e6, "2024-12-31", "2024-01-01")],
               SalesRevenueNet=[fact(90e6, "2023-12-31", "2023-01-01")])
    h = extract(cf)
    assert h.get("revenue", "FY2023").tag == "us-gaap:SalesRevenueNet"
    assert "fallback" in h.get("revenue", "FY2023").note
    assert any(r["fallback"] and r["period"] == "FY2023" for r in h.tag_log)


def test_ltm_from_ytd():
    cf = facts(Revenues=[
        fact(100e6, "2024-12-31", "2024-01-01"), fact(120e6, "2025-12-31", "2025-01-01", filed="2026-02-01"),
        fact(55e6, "2025-06-30", "2025-01-01", form="10-Q", filed="2025-08-01"),
        fact(70e6, "2026-06-30", "2026-01-01", form="10-Q", filed="2026-08-01")])
    h = extract(cf)
    assert h.ltm.label == "LTM 2026-06-30"
    v = h.get("revenue", h.ltm.label)
    assert v.value == 120 + 70 - 55 and "YTD" in v.formula


def test_ltm_tolerates_52_53_week_quarter_ends():
    cf = facts(Revenues=[
        fact(100e6, "2024-12-31", "2024-01-01"), fact(120e6, "2025-12-31", "2025-01-01", filed="2026-02-01"),
        fact(28e6, "2025-03-28", "2025-01-01", form="10-Q"),
        fact(31e6, "2026-04-03", "2026-01-01", form="10-Q", filed="2026-04-30")])
    h = extract(cf)
    assert h.v("revenue", "LTM 2026-04-03") == 120 + 31 - 28


def test_reporting_currency_detected():
    cf = facts(Revenues_eur=[fact(10e6, "2025-12-31", "2025-01-01", form="20-F")],
               Assets_eur=[fact(50e6, "2025-12-31", form="20-F")])
    h = extract(cf)
    assert h.currency == "EUR" and h.v("revenue", "FY2025") == 10.0


def test_current_debt_from_parts_without_double_counting():
    cf = facts(Revenues=[fact(120e6, "2025-12-31", "2025-01-01")],
               LongTermDebtCurrent=[fact(5e6, "2025-12-31")], CommercialPaper=[fact(3e6, "2025-12-31")],
               LongTermDebtNoncurrent=[fact(40e6, "2025-12-31")])
    h = standardise(extract(cf))
    assert h.v("debt_current", "FY2025") == 8
    assert h.v("total_debt", "FY2025") == 48
    assert any("CommercialPaper" in line for line in h.get("total_debt", "FY2025").trace())


def test_derived_gross_profit_is_traceable():
    cf = facts(Revenues=[fact(120e6, "2025-12-31", "2025-01-01")],
               CostOfRevenue=[fact(70e6, "2025-12-31", "2025-01-01")])
    gp = standardise(extract(cf)).get("gross_profit", "FY2025")
    assert gp.value == 50 and gp.formula == "revenue - cost_of_revenue" and "derived" in gp.note


def _with_cover(shares, end):
    cf = facts(Revenues=[fact(120e6, "2025-12-31", "2025-01-01"), fact(110e6, "2024-12-31", "2024-01-01")],
               WeightedAverageNumberOfSharesOutstandingBasic=[fact(1000e6, "2025-12-31", "2025-01-01")])
    cf["facts"]["us-gaap"]["WeightedAverageNumberOfSharesOutstandingBasic"]["units"] = {
        "shares": cf["facts"]["us-gaap"]["WeightedAverageNumberOfSharesOutstandingBasic"]["units"]["USD"]}
    cf["facts"]["dei"] = {"EntityCommonStockSharesOutstanding": {"units": {"shares": [
        fact(shares, end, form="10-K", filed="2026-02-01")]}}}
    return extract(cf)


def test_cover_page_shares_accepted_when_plausible():
    assert _with_cover(990e6, "2026-01-31").dei_shares.value == 990.0


def test_cover_page_shares_rejected_when_a_digit_is_wrong():
    h = _with_cover(99e6, "2026-01-31")  # BABA FY2026: 1.86bn tagged vs 18.6bn weighted
    assert h.dei_shares is None and any("rejected" in n for n in h.notes)


def test_cover_page_shares_rejected_when_stale():
    h = _with_cover(990e6, "2015-07-17")  # NKE: no longer tags the undimensioned cover-page count
    assert h.dei_shares is None and any("dated 2015-07-17" in n for n in h.notes)


def test_ebit_proxy_from_net_nonoperating_interest():
    """NKE tags neither operating income nor interest expense: EBIT = pre-tax - net interest income."""
    cf = facts(Revenues=[fact(46398e6, "2026-05-31", "2025-06-01")],
               IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest=[
                   fact(3900e6, "2026-05-31", "2025-06-01")],
               InterestIncomeExpenseNonoperatingNet=[fact(50e6, "2026-05-31", "2025-06-01")])
    h = standardise(extract(cf))
    v = h.get("operating_income", "FY2026")
    assert v.value == 3850.0 and "EBIT proxy" in v.formula
