"""Store each formula's computed result in an exported workbook.

openpyxl writes formulas without results. Excel recalculates them when editing is enabled, but anything that only
reads the stored results shows those cells blank: Excel's Protected View (the default for downloaded files), phone
and browser previews, Quick Look, many viewers. So every formula is evaluated here (pycel, the same engine as
exports/verify.py) and its result written into the cell's <v> element. The formulas stay live: openpyxl already
sets fullCalcOnLoad, so Excel recalculates on load and on every edit.
"""
from __future__ import annotations

import re
import tempfile
import zipfile
from html import unescape
from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape

from openpyxl import load_workbook
from openpyxl.utils import get_column_letter
from pycel import ExcelCompiler

ERRORS = {"#DIV/0!", "#VALUE!", "#REF!", "#NAME?", "#N/A", "#NUM!", "#NULL!"}
# a formula cell as openpyxl writes it: <c r="B5" s="28"><f>...</f><v /></c> (the <v> may be absent or empty)
CELL = re.compile(r'<c r="([A-Z]+[0-9]+)"([^>]*)><f>(.*?)</f>(?:<v\s*/>|<v></v>)?</c>', re.S)


def _v(value) -> tuple[str, str] | None:
    """(type attribute, <v> text) for a computed value; None leaves the cell without a stored result."""
    if value is None:
        return None
    if hasattr(value, "item"):  # numpy scalars from pycel
        value = value.item()
    if isinstance(value, bool):
        return ' t="b"', "1" if value else "0"
    if isinstance(value, (int, float)):
        if value != value or value in (float("inf"), float("-inf")):
            return ' t="e"', "#NUM!"
        return "", repr(float(value)) if isinstance(value, float) else str(value)
    text = str(value)
    if text in ERRORS:
        return ' t="e"', text
    return ' t="str"', escape(text)


def _grid(vals, r0: int, r1: int, c0: int, c1: int) -> tuple:
    """pycel returns a scalar for one cell and a flat tuple for one row or column: always a tuple of rows."""
    if r0 == r1 and c0 == c1:
        return ((vals,),)
    if not isinstance(vals[0], tuple):
        return (tuple(vals),) if r0 == r1 else tuple((v,) for v in vals)
    return vals


def results(xlsx: bytes) -> dict[str, dict[str, object]]:
    """{sheet title: {cell: computed value}} for every formula cell. Each sheet's formula block is evaluated as one
    range: pycel then builds its dependency graph once per sheet instead of once per cell (UBER 2.6 s, not 8.9 s;
    the same values)."""
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "model.xlsx"
        path.write_bytes(xlsx)
        wb = load_workbook(path)
        xl = ExcelCompiler(filename=str(path), plugins=["exports.pycel_ext"])
        out: dict[str, dict[str, object]] = {}
        for ws in wb.worksheets:
            cells = [c for row in ws.iter_rows() for c in row if isinstance(c.value, str) and c.value.startswith("=")]
            if not cells:
                continue
            r0, r1 = min(c.row for c in cells), max(c.row for c in cells)
            c0, c1 = min(c.column for c in cells), max(c.column for c in cells)
            vals = _grid(xl.evaluate(f"'{ws.title}'!{get_column_letter(c0)}{r0}:{get_column_letter(c1)}{r1}"),
                         r0, r1, c0, c1)
            out[ws.title] = {c.coordinate: vals[c.row - r0][c.column - c0] for c in cells}
        return out


def with_cached_values(xlsx: bytes) -> bytes:
    """The workbook with every formula's result stored next to the formula."""
    vals = results(xlsx)
    src = zipfile.ZipFile(BytesIO(xlsx))
    titles = re.findall(r'<sheet name="([^"]*)"', src.read("xl/workbook.xml").decode("utf-8"))
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as dst:
        for item in src.infolist():
            data = src.read(item.filename)
            m = re.fullmatch(r"xl/worksheets/sheet(\d+)\.xml", item.filename)
            if m and int(m.group(1)) <= len(titles):
                sheet_vals = vals.get(unescape(titles[int(m.group(1)) - 1]), {})

                def fill(mm: re.Match) -> str:
                    ref, attrs, formula = mm.group(1), re.sub(r'\s+t="[^"]*"', "", mm.group(2)), mm.group(3)
                    tv = _v(sheet_vals.get(ref))
                    if tv is None:
                        return mm.group(0)
                    return f'<c r="{ref}"{attrs}{tv[0]}><f>{formula}</f><v>{tv[1]}</v></c>'
                data = CELL.sub(fill, data.decode("utf-8")).encode("utf-8")
            dst.writestr(item, data)
    return buf.getvalue()
