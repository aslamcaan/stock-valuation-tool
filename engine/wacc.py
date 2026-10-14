"""WACC (pure). CAPM cost of equity with a country risk premium; after-tax cost of debt; market weights.

Every component is a Value with its formula and inputs so the report can trace the WACC end to end.
"""
from __future__ import annotations

from dataclasses import dataclass

from engine.values import MILLIONS, RATIO, Value, calc


@dataclass(frozen=True)
class WaccInputs:
    risk_free: Value
    erp: Value
    beta_regression: Value | None
    unlevered_beta_industry: Value | None
    marginal_tax_rate: Value
    crp: Value                      # revenue-weighted country risk premium (relative to the US)
    pre_tax_cost_of_debt: Value
    market_cap: Value               # equity value (US$m)
    debt: Value                     # debt incl. leases (book value as proxy for market value)
    beta_choice: str = "industry"   # "industry" (default) or "regression"
    beta_override: float | None = None


@dataclass(frozen=True)
class WaccResult:
    wacc: Value
    cost_of_equity: Value
    after_tax_cost_of_debt: Value
    beta: Value
    relevered_industry_beta: Value | None
    weight_equity: Value
    weight_debt: Value
    de_ratio: Value
    inputs: WaccInputs


def relever(unlevered: Value, de: Value, tax: Value) -> Value:
    return calc(lambda bu, d, t: bu * (1 + (1 - t) * d), "unlevered beta x (1 + (1 - tax) x D/E)", "current",
                RATIO, None, unlevered_beta=unlevered, de_ratio=de, tax_rate=tax)


def synthetic_rating(interest_cover: float | None, table: list[dict]) -> dict:
    """Rating band for an interest coverage ratio (Damodaran's synthetic rating table)."""
    if interest_cover is None:
        return {"rating": "not rated (no interest expense)", "spread": table[-1]["spread"]}
    for row in table:
        if row["min"] <= interest_cover <= row["max"] + 1e-9:
            return row
    return table[-1] if interest_cover > table[-1]["min"] else table[0]


def compute_wacc(i: WaccInputs) -> WaccResult:
    de = calc(lambda d, e: d / e, "debt / market cap", "current", RATIO, None, debt=i.debt, market_cap=i.market_cap)
    relevered = relever(i.unlevered_beta_industry, de, i.marginal_tax_rate) if i.unlevered_beta_industry else None
    if i.beta_override is not None:
        beta = Value(i.beta_override, None, RATIO, "current", "user override")
    elif i.beta_choice == "regression" and i.beta_regression is not None:
        beta = i.beta_regression
    elif relevered is not None and relevered.value is not None:
        beta = relevered
    elif i.beta_regression is not None:
        beta = i.beta_regression.with_note("industry beta unavailable; regression beta used")
    else:
        raise ValueError("no beta available")
    ke = calc(lambda rf, b, erp, crp: rf + b * erp + crp, "risk-free + beta x ERP + CRP", "current", RATIO, None,
              risk_free=i.risk_free, beta=beta, erp=i.erp, crp=i.crp)
    kd = calc(lambda k, t: k * (1 - t), "pre-tax cost of debt x (1 - marginal tax)", "current", RATIO, None,
              pre_tax_cost_of_debt=i.pre_tax_cost_of_debt, tax_rate=i.marginal_tax_rate)
    total = calc(lambda e, d: e + d, "market cap + debt", "current", MILLIONS, "USD", market_cap=i.market_cap,
                 debt=i.debt)
    we = calc(lambda e, v: e / v, "market cap / (market cap + debt)", "current", RATIO, None,
              market_cap=i.market_cap, total=total)
    wd = calc(lambda d, v: d / v, "debt / (market cap + debt)", "current", RATIO, None, debt=i.debt, total=total)
    wacc = calc(lambda a, b, c, d: a * b + c * d, "E/V x cost of equity + D/V x after-tax cost of debt", "current",
                RATIO, None, weight_equity=we, cost_of_equity=ke, weight_debt=wd, after_tax_cost_of_debt=kd)
    return WaccResult(wacc, ke, kd, beta, relevered, we, wd, de, i)
