"""Open an exported workbook in real Microsoft Excel, recalculate, and report errors and the check rows.
Windows + Excel only (pywin32). Usage: python scripts/excel_check.py path.xlsx"""
import sys
from pathlib import Path

import win32com.client as win32

ERRORS = {-2146826281: "#DIV/0!", -2146826246: "#N/A", -2146826259: "#NAME?", -2146826288: "#NULL!",
          -2146826252: "#NUM!", -2146826265: "#REF!", -2146826273: "#VALUE!"}


def check(path: str) -> dict:
    xl = win32.DispatchEx("Excel.Application")
    xl.Visible = False
    xl.DisplayAlerts = False
    wb = xl.Workbooks.Open(str(Path(path).resolve()))
    try:
        xl.CalculateFull()
        errors, formulas = [], 0
        for ws in wb.Worksheets:
            used = ws.UsedRange
            for cell in used:
                if cell.HasFormula:
                    formulas += 1
                    v = cell.Value
                    if isinstance(v, int) and v in ERRORS:
                        errors.append(f"{ws.Name}!{cell.Address}: {ERRORS[v]}")
        s = wb.Worksheets("Summary")
        return {"formulas": formulas, "errors": errors[:10], "fair_value": s.Range("B10").Value,
                "dcf_check": s.Range("B15").Value, "fair_value_check": s.Range("B17").Value,
                "verdict": s.Range("B12").Value}
    finally:
        wb.Close(SaveChanges=False)
        xl.Quit()


if __name__ == "__main__":
    print(check(sys.argv[1]))
