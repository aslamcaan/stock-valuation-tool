"""FMP statements: EDGAR cross-check values and the LTM fallback for filers without interim XBRL.

FMP reports in units of currency; values here are converted to millions.
"""
from __future__ import annotations

from datetime import date

from engine.model import Period
from engine.values import MILLIONS, SHARES_M, Value

SOURCE = "FMP"

# standard line -> (FMP field, statement endpoint, sign). Capex and outflows are negative in FMP.
FIELDS = {
    "revenue": ("revenue", "income", 1), "cost_of_revenue": ("costOfRevenue", "income", 1),
    "operating_income": ("operatingIncome", "income", 1), "pretax_income": ("incomeBeforeTax", "income", 1),
    "income_tax": ("incomeTaxExpense", "income", 1), "net_income_attributable": ("netIncome", "income", 1),
    "interest_expense": ("interestExpense", "income", 1),
    "shares_diluted_weighted": ("weightedAverageShsOutDil", "income", 1),
    "shares_basic_weighted": ("weightedAverageShsOut", "income", 1),
    "cfo": ("operatingCashFlow", "cash", 1), "capex": ("capitalExpenditure", "cash", -1),
    "d_and_a": ("depreciationAndAmortization", "cash", 1), "sbc": ("stockBasedCompensation", "cash", 1),
    "buybacks": ("commonStockRepurchased", "cash", -1), "dividends_paid": ("commonDividendsPaid", "cash", -1),
    "cash": ("cashAndCashEquivalents", "balance", 1), "short_term_investments": ("shortTermInvestments", "balance", 1),
    "total_assets": ("totalAssets", "balance", 1), "total_liabilities": ("totalLiabilities", "balance", 1),
    "total_equity": ("totalEquity", "balance", 1), "parent_equity": ("totalStockholdersEquity", "balance", 1),
    "debt_current": ("shortTermDebt", "balance", 1), "long_term_debt": ("longTermDebt", "balance", 1),
    "fmp_total_debt": ("totalDebt", "balance", 1), "receivables": ("netReceivables", "balance", 1),
    "inventory": ("inventory", "balance", 1), "accounts_payable": ("accountPayables", "balance", 1),
    "current_assets": ("totalCurrentAssets", "balance", 1),
    "current_liabilities": ("totalCurrentLiabilities", "balance", 1),
}
SHARE_FIELDS = {"shares_diluted_weighted", "shares_basic_weighted"}


def _row_for(rows: list[dict], end: date, tol_days: int = 10) -> dict | None:
    for r in rows or []:
        try:
            d = date.fromisoformat(r["date"][:10])
        except (KeyError, ValueError):
            continue
        if abs((d - end).days) <= tol_days:
            return r
    return None


def annual_values(income: list[dict], balance: list[dict], cash: list[dict], end: date) -> dict[str, float | None]:
    """FMP annual figures (millions) for the fiscal year ending near `end`."""
    stmts = {"income": _row_for(income, end), "balance": _row_for(balance, end), "cash": _row_for(cash, end)}
    out: dict[str, float | None] = {}
    for line, (fld, st, sign) in FIELDS.items():
        r = stmts[st]
        v = None if r is None or r.get(fld) is None else sign * float(r[fld]) / 1e6
        out[line] = v
    return out


def ltm_from_quarters(income_q: list[dict], cash_q: list[dict], balance_q: list[dict], after: date,
                      currency: str, fetched_at: str | None) -> tuple[Period | None, dict[str, Value]]:
    """Sum the last four quarters of income/cash flow, take the latest balance sheet. Requires the latest
    quarter to end after `after` (the last fiscal year end); otherwise LTM adds nothing."""
    def recent(rows):
        rows = sorted((r for r in rows or [] if r.get("date")), key=lambda r: r["date"], reverse=True)
        return rows[:4]

    iq, cq = recent(income_q), recent(cash_q)
    if len(iq) < 4 or date.fromisoformat(iq[0]["date"][:10]) <= after:
        return None, {}
    ends = [date.fromisoformat(r["date"][:10]) for r in iq]
    if any(not 80 <= (a - b).days <= 100 for a, b in zip(ends, ends[1:])):
        return None, {}  # quarters not consecutive: summing them would not be twelve months
    cash_ok = len(cq) == 4 and [r["date"][:10] for r in cq] == [r["date"][:10] for r in iq]
    end = ends[0]
    label = f"LTM {end.isoformat()}"
    period = Period(label, end, None, "LTM", source="FMP")
    src_q = {"income": iq, "cash": cq if cash_ok else None,
             "balance": [_row_for(balance_q, end)] if _row_for(balance_q, end) else None}
    out: dict[str, Value] = {}
    for line, (fld, st, sign) in FIELDS.items():
        rows = src_q[st]
        if not rows or any(r.get(fld) is None for r in rows) or line == "fmp_total_debt":
            continue
        unit = SHARES_M if line in SHARE_FIELDS else MILLIONS
        if st == "balance":
            val = sign * float(rows[0][fld]) / 1e6
            how = f"FMP quarterly balance sheet at {end}"
        elif line in SHARE_FIELDS:
            val = float(rows[0][fld]) / 1e6
            how = f"FMP latest quarter weighted shares to {end}"
        else:
            val = sign * sum(float(r[fld]) for r in rows) / 1e6
            how = "sum of last four FMP quarters: " + ", ".join(r["date"][:10] for r in rows)
        out[line] = Value(val, None if unit == SHARES_M else currency, unit, label, SOURCE, tag=f"fmp:{fld}",
                          fetched_at=fetched_at, note=how)
    return period, out
