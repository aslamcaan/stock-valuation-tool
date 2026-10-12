"""Extract tests/fixtures/grab_model.xlsx into tests/fixtures/grab_expected.json with cell references.

Run: python scripts/extract_grab_model.py
"""
from __future__ import annotations

import json
from pathlib import Path

import openpyxl

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "tests" / "fixtures" / "grab_model.xlsx"
OUT = ROOT / "tests" / "fixtures" / "grab_expected.json"

YEARS = {"B": "FY2025A", "C": "FY2026E", "D": "FY2027E", "E": "FY2028E", "F": "FY2029E", "G": "FY2030E"}
FORECAST_COLS = "CDEFG"


def extract() -> dict:
    wb_f = openpyxl.load_workbook(SRC, data_only=False)
    wb_v = openpyxl.load_workbook(SRC, data_only=True)
    ws_f, ws_v = wb_f.active, wb_v.active

    def cell(ref: str) -> dict:
        f = ws_f[ref].value
        out = {"value": ws_v[ref].value, "cell": f"'{ws_f.title}'!{ref}"}
        if isinstance(f, str) and f.startswith("="):
            out["formula"] = f
        return out

    def row(r: int, cols: str) -> dict:
        return {YEARS[c]: cell(f"{c}{r}") for c in cols if ws_v[f"{c}{r}"].value is not None}

    expected = {
        "source_file": "tests/fixtures/grab_model.xlsx",
        "sheet": ws_f.title,
        "title": ws_v["A1"].value.strip(),
        "prepared": ws_v["A2"].value.strip(),
        "units": "US$ millions, except per-share values",
        "historicals": {
            "FY2025A": {
                "revenue": cell("B13"),
                "ebitda": cell("B14"),
                "d_and_a": cell("B15"),
                "capex": cell("B20"),
                "ebit": cell("B16"),
            },
            "balance_sheet": {
                "cash_and_investments": cell("B53"),
                "total_debt": cell("B27"),
                "shares_outstanding_m": cell("B25"),
            },
            "market": {"share_price": cell("B24")},
            "notes": ("FY2025A EBITDA, D&A and capex are the FY2025 ratios in rows 7-9 applied to revenue, "
                      "not separately reported figures. EBITDA appears to be Grab's adjusted (non-IFRS) EBITDA."),
        },
        "assumptions": {
            "revenue_growth": row(6, FORECAST_COLS),
            "ebitda_margin": row(7, "B" + FORECAST_COLS),
            "d_and_a_pct_revenue": row(8, "B" + FORECAST_COLS),
            "capex_pct_revenue": row(9, "B" + FORECAST_COLS),
            "tax_rate": row(10, "B" + FORECAST_COLS),
            "risk_free_rate": cell("B31"),
            "beta": cell("B32"),
            "equity_risk_premium": cell("B33"),
            "pre_tax_cost_of_debt": cell("B34"),
            "debt_tax_rate": cell("B36"),
            "terminal_growth": cell("B40"),
        },
        "conventions": {
            "forecast_years": ["FY2026E", "FY2027E", "FY2028E", "FY2029E", "FY2030E"],
            "discounting": "end_of_year",  # discount periods 1..5 in C44:G44, no mid-year adjustment
            "discount_periods": [ws_v[f"{c}44"].value for c in FORECAST_COLS],
            "stub_period": False,
            "fcf_definition": "NOPAT + D&A - capex (EBIT taxed at forecast tax rate); no working capital, SBC not deducted",
            "terminal_value": "Gordon growth on FY2030E UFCF: UFCF*(1+g)/(WACC-g), discounted with the FY2030 factor",
            "wacc_weights": "market cap (price x shares) and book total debt",
            "equity_bridge": "EV + cash & investments - total debt",
            "share_count": "shares outstanding (B25), no dilution adjustment",
        },
        "computed": {
            "ufcf": row(21, FORECAST_COLS),
            "market_cap": cell("B26"),
            "cost_of_equity": cell("B35"),
            "wacc": cell("B37"),
            "terminal_value": cell("B41"),
            "pv_terminal_value": cell("G47"),
            "sum_pv_fcf": cell("B50"),
            "enterprise_value": cell("B52"),
            "equity_value": cell("B55"),
            "value_per_share": cell("B57"),
            "upside": cell("B59"),
        },
        "sensitivity": {
            "description": "Value per share: terminal growth (rows B63:B67) x WACC (columns C62:G62), Excel data table",
            "terminal_growth": [ws_v[f"B{r}"].value for r in range(63, 68)],
            "wacc": [ws_v[f"{c}62"].value for c in FORECAST_COLS],
            "value_per_share": [[ws_v[f"{c}{r}"].value for c in FORECAST_COLS] for r in range(63, 68)],
            "cells": "C63:G67",
        },
    }
    return expected


if __name__ == "__main__":
    OUT.write_text(json.dumps(extract(), indent=2), encoding="utf-8")
    print(f"wrote {OUT}")
