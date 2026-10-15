"""Formatting helpers for the report: UK number formats and click-to-trace HTML.

Every number shown through `cell()` / `traced_table()` carries its provenance as a hover tooltip (source, filing,
tag, fetch time, or formula and inputs for calculated numbers). `metric()` adds the same trace to st.metric help.
"""
from __future__ import annotations

import html

from engine.values import DAYS, MILLIONS, MULTIPLE, PER_SHARE, RATIO, SHARES_M, Value

STATE_ICON = {"done": "✓", "running": "◌", "failed": "✗", "waiting": "·", "skipped": "–"}
STATE_COLOUR = {"done": "#1a7f37", "running": "#0969da", "failed": "#cf222e", "waiting": "#8c959f", "skipped": "#8c959f"}
FLAG_ICON = {"hard_stop": "⛔", "red": "🔴", "amber": "🟠", "info": "ℹ️"}

CSS = """
<style>
.vt-table {border-collapse: collapse; width: 100%; font-size: 0.86rem; margin-bottom: 0.6rem;}
.vt-table th {text-align: right; padding: 4px 8px; border-bottom: 2px solid #d0d7de; color: #57606a; font-weight: 600;}
.vt-table th:first-child, .vt-table td:first-child {text-align: left;}
.vt-table td {text-align: right; padding: 3px 8px; border-bottom: 1px solid #eaeef2;}
.vt-table td.tr {cursor: help; text-decoration: underline dotted #8c959f;}
.vt-table tr.sub td {color: #57606a; font-style: italic;}
.vt-card {border: 1px solid #d0d7de; border-radius: 8px; padding: 1rem 1.2rem; background: #ffffff;}
.vt-verdict {font-size: 1.6rem; font-weight: 700;}
.vt-muted {color: #57606a; font-size: 0.85rem;}
.vt-desk {font-family: ui-monospace, monospace; font-size: 0.9rem; line-height: 1.6;}
</style>
"""


def money(x: float | None, nd: int = 2, prefix: str = "$") -> str:
    if x is None:
        return "–"
    return f"{'-' if x < 0 else ''}{prefix}{abs(x):,.{nd}f}"


def millions(x: float | None) -> str:
    if x is None:
        return "–"
    return f"({abs(x):,.0f})" if x < 0 else f"{x:,.0f}"


def pct(x: float | None, nd: int = 1) -> str:
    return "–" if x is None else f"{x * 100:.{nd}f}%"


def mult(x: float | None) -> str:
    return "–" if x is None else f"{x:.1f}x"


def fmt_value(v: Value | None) -> str:
    if v is None or v.value is None:
        return "–"
    if v.unit == RATIO:
        return pct(v.value)
    if v.unit == MULTIPLE:
        return mult(v.value)
    if v.unit == PER_SHARE:
        return money(v.value)
    if v.unit == DAYS:
        return f"{v.value:,.0f}"
    if v.unit in (MILLIONS, SHARES_M):
        return millions(v.value)
    return f"{v.value:,.2f}"


def trace_text(v: Value | None) -> str:
    if v is None:
        return "not available"
    return "\n".join(v.trace())


def cell(v: Value | None, text: str | None = None) -> str:
    shown = html.escape(text if text is not None else fmt_value(v))
    if v is None or v.value is None:
        return f"<td title=\"{html.escape(v.note or 'not available') if v else 'not available'}\">{shown}</td>"
    return f"<td class=\"tr\" title=\"{html.escape(trace_text(v))}\">{shown}</td>"


def traced_table(rows: list[tuple[str, list[Value | None]]], headers: list[str],
                 formatter=None, sub_rows: set[str] | None = None) -> str:
    """rows: (label, [Value per column]). Hover any number to see where it came from."""
    head = "".join(f"<th>{html.escape(h)}</th>" for h in headers)
    body = []
    for label, vals in rows:
        cls = " class=\"sub\"" if sub_rows and label in sub_rows else ""
        cells = "".join(cell(v, formatter(v) if formatter and v is not None and v.value is not None else None)
                        for v in vals)
        body.append(f"<tr{cls}><td>{html.escape(label)}</td>{cells}</tr>")
    return f"<table class=\"vt-table\"><thead><tr><th></th>{head}</tr></thead><tbody>{''.join(body)}</tbody></table>"


def plain_table(rows: list[list[str]], headers: list[str]) -> str:
    head = "".join(f"<th>{html.escape(h)}</th>" for h in headers)
    body = "".join("<tr>" + "".join(f"<td>{html.escape(str(c))}</td>" for c in r) + "</tr>" for r in rows)
    return f"<table class=\"vt-table\"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def calc_value(x: float | None, unit: str, formula: str, currency: str | None = "USD") -> Value:
    """Wrap a computed number that is not already a Value, so it can still be traced."""
    return Value(x, currency, unit, "current", "calculated", formula=formula)
