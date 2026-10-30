"""Recalculate every formula in an exported workbook (pycel) and report errors and the check rows."""
from __future__ import annotations

import sys
from pathlib import Path

from openpyxl import load_workbook
from pycel import ExcelCompiler

ERRORS = ("#DIV/0!", "#VALUE!", "#REF!", "#NAME?", "#N/A", "#NUM!", "#NULL!")


def verify(path: str | Path) -> dict:
    wb = load_workbook(path)
    xl = ExcelCompiler(filename=str(path), plugins=["exports.pycel_ext"])
    formulas, errors = 0, []
    for ws in wb.worksheets:
        for row in ws.iter_rows():
            for c in row:
                if isinstance(c.value, str) and c.value.startswith("="):
                    formulas += 1
                    val = xl.evaluate(f"'{ws.title}'!{c.coordinate}")
                    if isinstance(val, str) and val in ERRORS:
                        errors.append(f"{ws.title}!{c.coordinate}: {val} ({c.value[:80]})")
    get = lambda ref: xl.evaluate(ref)  # noqa: E731
    if "Metrics" in wb.sheetnames and "Historicals" not in wb.sheetnames:  # financial-sector workbook
        su = wb["Summary"]
        fv_row = next(r for r in range(5, 60) if su[f"A{r}"].value == "Fair value (weighted blend)")
        checks = [get(f"Summary!B{r}") for r in range(fv_row + 5, fv_row + 12)
                  if str(su[f"A{r}"].value or "").startswith("Check:") and su[f"B{r}"].data_type == "f"]
        return {"formulas": formulas, "errors": errors, "fair_value": get(f"Summary!B{fv_row}"),
                "fair_value_check": get(f"Summary!B{fv_row + 5}"), "method_checks": checks,
                "verdict": get(f"Summary!B{fv_row + 2}")}
    return {"formulas": formulas, "errors": errors, "excel_dcf": get("Summary!B6"),
            "dcf_check": get("Summary!B15"), "fair_value": get("Summary!B10"), "fair_value_check": get("Summary!B17"),
            "verdict": get("Summary!B12")}


if __name__ == "__main__":
    print(verify(sys.argv[1]))
