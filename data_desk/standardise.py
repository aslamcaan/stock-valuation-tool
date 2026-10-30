"""Derived lines that complete the standardised statements, each a traceable calculation.

Run after extraction. A derived line only fills a period where the reported line is missing, except
for purely calculated aggregates (total_debt, lease_liabilities, net_debt, ebitda, fcf, ...),
which are always computed from their components.

Total debt, in order of preference:
1. a reported all-in total (current + non-current), e.g. DebtLongtermAndShorttermCombinedAmount;
2. balance-sheet lines: (current portion of LTD + short-term borrowings, or reported current debt)
   + non-current long-term debt;
3. long-term debt including current maturities + short-term borrowings;
4. total borrowings as reported (IFRS Borrowings).
Finance leases are added to "debt incl. leases" only when the debt tags used do not already include them.
"""
from __future__ import annotations

from engine.dates import has
from engine.model import Historicals
from engine.values import MILLIONS, Value, calc

DERIVED_LABELS = {
    "total_debt": "Total debt",
    "lease_liabilities": "Lease liabilities not already in debt",
    "total_debt_incl_leases": "Total debt incl. leases",
    "debt_for_valuation": "Debt for valuation (US GAAP: excl. operating leases; IFRS: incl. leases)",
    "cash_and_investments": "Cash and short-term investments",
    "net_debt": "Net debt (incl. leases)",
    "ebitda": "EBITDA (operating income + D&A)",
    "fcf": "Free cash flow (CFO - capex)",
    "fcf_after_sbc": "Free cash flow after SBC",
    "non_operating_and_tax_gap": "Net income minus operating income",
}

AMBIGUOUS_DEBT = "debt tags ambiguous"
CARRY_FORWARD_TO_LTM = ("operating_lease_liabilities", "finance_lease_liabilities")
LEASE_IN_TAG = ("CapitalLease", "FinanceLease")


def _z(h: Historicals, line: str, period: str, currency: str) -> Value:
    """Reported value, or an explicit zero when the line is simply not reported (e.g. no NCI)."""
    v = h.get(line, period)
    if has(v):
        return v
    return Value(0.0, currency, MILLIONS, period, "assumed zero", note=f"{line} not reported; treated as 0")


def _fill(h: Historicals, line: str, period: str, value: Value) -> None:
    if not has(h.get(line, period)) and has(value):
        h.lines.setdefault(line, {})[period] = value.with_note("derived: not reported directly")


def _set(h: Historicals, line: str, period: str, value: Value) -> None:
    h.lines.setdefault(line, {})[period] = value


def _includes_finance_leases(v: Value) -> bool:
    tags = [v.tag or ""] + [x.tag or "" for x in v.inputs] + [y.tag or "" for x in v.inputs for y in x.inputs]
    return any(k in t for t in tags for k in LEASE_IN_TAG)


def _total_debt(h: Historicals, p: str, c: str) -> Value | None:
    """See module docstring for the order of preference."""
    g = lambda name: h.get(name, p)  # noqa: E731
    if has(g("debt_total_reported")):
        return g("debt_total_reported")
    if has(g("current_portion_ltd")) or has(g("short_term_borrowings")):
        current = calc(lambda a, b: a + b, "current_portion_ltd + short_term_borrowings", p, MILLIONS, c,
                       current_portion_ltd=_z(h, "current_portion_ltd", p, c),
                       short_term_borrowings=_z(h, "short_term_borrowings", p, c))
    elif has(g("debt_current")):
        current = g("debt_current")
    else:
        current = None
    lt, incl = g("long_term_debt"), g("ltd_incl_current")
    ambiguous = (has(lt) and has(incl) and has(current) and current.value > 0
                 and abs(lt.value - incl.value) <= 0.005 * max(abs(incl.value), 1.0))
    if has(lt) and not ambiguous:
        return calc(lambda a, b: a + b, "current debt + long_term_debt", p, MILLIONS, c,
                    current_debt=current or _z(h, "debt_current", p, c), long_term_debt=lt)
    if ambiguous:
        return calc(lambda a, b: a + b, "ltd_incl_current + short_term_borrowings", p, MILLIONS, c,
                    ltd_incl_current=incl, short_term_borrowings=_z(h, "short_term_borrowings", p, c)).with_note(
            f"{AMBIGUOUS_DEBT}: the filer reports the same figure ({lt.value:,.0f}) as non-current long-term debt and "
            f"as long-term debt including current maturities, so the current portion is not added again")
    if has(incl):
        return calc(lambda a, b: a + b, "ltd_incl_current + short_term_borrowings", p, MILLIONS, c,
                    ltd_incl_current=incl, short_term_borrowings=_z(h, "short_term_borrowings", p, c))
    if has(g("total_borrowings")):
        return g("total_borrowings")
    return current


def standardise(h: Historicals) -> Historicals:
    c = h.currency
    if h.ltm and h.fy_labels and h.ltm.source == "EDGAR":
        last = h.fy_labels[-1]
        for line in CARRY_FORWARD_TO_LTM:
            fy_v = h.get(line, last)
            if has(fy_v) and h.get(line, h.ltm.label) is None:
                h.lines.setdefault(line, {})[h.ltm.label] = fy_v.with_note(
                    f"carried forward from {last}: not reported in the interim filing")

    for period in h.periods:
        p = period.label
        g = lambda name: h.get(name, p)  # noqa: E731

        # --- fill gaps in reported lines -------------------------------------------------------------
        if not has(g("operating_income")) and has(g("pretax_income")) and has(g("interest_expense")):
            v = calc(lambda pt, ie: pt + ie, "pretax_income + interest_expense (EBIT proxy)", p, MILLIONS, c,
                     pretax_income=g("pretax_income"), interest_expense=g("interest_expense"))
            _fill(h, "operating_income", p, v.with_note(
                "operating income not reported: EBIT proxy includes non-operating items such as equity-affiliate income"))
        elif not has(g("operating_income")) and has(g("pretax_income")) and has(g("net_interest_nonoperating")):
            v = calc(lambda pt, ni: pt - ni, "pretax_income - net non-operating interest income (EBIT proxy)", p,
                     MILLIONS, c, pretax_income=g("pretax_income"),
                     net_interest_nonoperating=g("net_interest_nonoperating"))
            _fill(h, "operating_income", p, v.with_note(
                "operating income not reported: EBIT proxy includes non-operating items such as equity-affiliate income"))
        if has(g("revenue")) and has(g("cost_of_revenue")):
            _fill(h, "gross_profit", p, calc(lambda r, k: r - k, "revenue - cost_of_revenue", p, MILLIONS, c,
                                             revenue=g("revenue"), cost_of_revenue=g("cost_of_revenue")))
        if not has(g("cash")) and has(g("cash_end_cf")):
            _fill(h, "cash", p, g("cash_end_cf").with_note(
                "balance-sheet cash not tagged: cash-flow ending cash used (may include restricted cash)"))
        if has(g("parent_equity")) and not has(g("total_equity")):
            _fill(h, "total_equity", p, calc(lambda e, m: e + m, "parent_equity + minority_interest", p, MILLIONS, c,
                                             parent_equity=g("parent_equity"),
                                             minority_interest=_z(h, "minority_interest", p, c)))
        if has(g("total_equity")) and has(g("parent_equity")):
            _fill(h, "minority_interest", p, calc(lambda t, e: t - e, "total_equity - parent_equity", p, MILLIONS, c,
                                                  total_equity=g("total_equity"), parent_equity=g("parent_equity")))
        if has(g("total_investments_ifrs")) and has(g("noncurrent_investments_ifrs")):
            _fill(h, "short_term_investments", p,
                  calc(lambda t, n: t - n, "investments (total) - non-current investments", p, MILLIONS, c,
                       total=g("total_investments_ifrs"), non_current=g("noncurrent_investments_ifrs")))
        if has(g("liabilities_and_equity")) and has(g("total_equity")):
            _fill(h, "total_liabilities", p,
                  calc(lambda le, e, t: le - e - t, "liabilities_and_equity - total_equity - temporary_equity", p,
                       MILLIONS, c, liabilities_and_equity=g("liabilities_and_equity"), total_equity=g("total_equity"),
                       temporary_equity=_z(h, "temporary_equity", p, c)))
        if has(g("current_portion_ltd")) or has(g("short_term_borrowings")):
            _fill(h, "debt_current", p, calc(lambda a, b: a + b, "current_portion_ltd + short_term_borrowings", p,
                                             MILLIONS, c, current_portion_ltd=_z(h, "current_portion_ltd", p, c),
                                             short_term_borrowings=_z(h, "short_term_borrowings", p, c)))

        # --- always-calculated aggregates -------------------------------------------------------------
        debt = _total_debt(h, p, c)
        if has(debt):
            _set(h, "total_debt", p, debt)
        fin_in_debt = has(debt) and _includes_finance_leases(debt)
        if period.source == "FMP":
            pass  # FMP debt fields already include leases; adding lease balances would double count
        elif has(g("operating_lease_liabilities")) or (has(g("finance_lease_liabilities")) and not fin_in_debt):
            fin = Value(0.0, c, MILLIONS, p, "excluded", note="finance leases already included in debt tags") \
                if fin_in_debt else _z(h, "finance_lease_liabilities", p, c)
            _set(h, "lease_liabilities", p,
                 calc(lambda o, f: o + f, "operating_lease_liabilities + finance_lease_liabilities", p, MILLIONS, c,
                      operating_lease_liabilities=_z(h, "operating_lease_liabilities", p, c),
                      finance_lease_liabilities=fin))
        if has(g("total_debt")):
            _set(h, "total_debt_incl_leases", p,
                 calc(lambda d, l_: d + l_, "total_debt + lease_liabilities", p, MILLIONS, c,
                      total_debt=g("total_debt"), lease_liabilities=_z(h, "lease_liabilities", p, c)))
        if has(g("total_debt")):
            if h.taxonomy == "ifrs-full":
                # IFRS 16: lease costs are depreciation + interest, not operating expense, so leases are debt
                _set(h, "debt_for_valuation", p, g("total_debt_incl_leases").with_note(
                    "IFRS 16: all lease liabilities are debt (operating profit excludes lease interest)"))
            else:
                fin = (Value(0.0, c, MILLIONS, p, "excluded", note="finance leases already in debt tags")
                       if fin_in_debt else _z(h, "finance_lease_liabilities", p, c))
                _set(h, "debt_for_valuation", p, calc(
                    lambda d, f: d + f, "total_debt + finance_lease_liabilities", p, MILLIONS, c,
                    total_debt=g("total_debt"), finance_lease_liabilities=fin).with_note(
                    "US GAAP: operating lease costs are already deducted in operating income, so operating lease "
                    "liabilities are not added as debt"))
        if has(g("cash")):
            _set(h, "cash_and_investments", p,
                 calc(lambda a, b: a + b, "cash + short_term_investments", p, MILLIONS, c,
                      cash=g("cash"), short_term_investments=_z(h, "short_term_investments", p, c)))
        if has(g("total_debt_incl_leases")) and has(g("cash_and_investments")):
            _set(h, "net_debt", p, calc(lambda d, k: d - k, "total_debt_incl_leases - cash_and_investments", p,
                                        MILLIONS, c, total_debt_incl_leases=g("total_debt_incl_leases"),
                                        cash_and_investments=g("cash_and_investments")))
        if has(g("operating_income")) and has(g("d_and_a")):
            _set(h, "ebitda", p, calc(lambda o, d: o + d, "operating_income + d_and_a", p, MILLIONS, c,
                                      operating_income=g("operating_income"), d_and_a=g("d_and_a")))
        if has(g("cfo")) and has(g("capex")):
            _set(h, "fcf", p, calc(lambda o, k: o - k, "cfo - capex", p, MILLIONS, c, cfo=g("cfo"), capex=g("capex")))
            if has(g("sbc")):
                _set(h, "fcf_after_sbc", p, calc(lambda f, s: f - s, "fcf - sbc", p, MILLIONS, c,
                                                 fcf=g("fcf"), sbc=g("sbc")))
        if has(g("net_income_attributable")) and has(g("operating_income")):
            _set(h, "non_operating_and_tax_gap", p,
                 calc(lambda n, o: n - o, "net_income_attributable - operating_income", p, MILLIONS, c,
                      net_income_attributable=g("net_income_attributable"), operating_income=g("operating_income")))
    return h
