"""Formatting helpers for the report: UK number formats and click-to-trace HTML.

Every number shown through `cell()` / `traced_table()` carries its provenance as a hover tooltip (source, filing,
tag, fetch time, or formula and inputs for calculated numbers). `metric()` adds the same trace to st.metric help.
"""
from __future__ import annotations

import html

from engine.values import DAYS, MILLIONS, MULTIPLE, PER_SHARE, RATIO, SHARES_M, Value
from ui.theme import ACCENT, AMBER, CSS, GREEN, MUTED, RED  # noqa: F401  (re-exported for the views)

STATE_ICON = {"done": "✓", "running": "◌", "failed": "✗", "waiting": "·", "skipped": "–"}
STATE_COLOUR = {"done": GREEN, "running": ACCENT, "failed": RED, "waiting": MUTED, "skipped": MUTED}
FLAG_ICON = {"hard_stop": "⛔", "red": "🔴", "amber": "🟠", "info": "ℹ️"}  # plain-text logs only; the UI uses chips


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
    return (f"<div class=\"vt-scroll\"><table class=\"vt-table\"><thead><tr><th></th>{head}</tr></thead>"
            f"<tbody>{''.join(body)}</tbody></table></div>")


def plain_table(rows: list[list[str]], headers: list[str]) -> str:
    head = "".join(f"<th>{html.escape(h)}</th>" for h in headers)
    body = "".join("<tr>" + "".join(f"<td>{html.escape(str(c))}</td>" for c in r) + "</tr>" for r in rows)
    # prose cells (evidence, challenges, notes) read left-aligned in the text face; figures stay right-aligned
    cls = "vt-table text" if any(len(str(c)) > 40 for r in rows for c in r) else "vt-table"
    return (f"<div class=\"vt-scroll\"><table class=\"{cls}\"><thead><tr>{head}</tr></thead>"
            f"<tbody>{body}</tbody></table></div>")


def calc_value(x: float | None, unit: str, formula: str, currency: str | None = "USD") -> Value:
    """Wrap a computed number that is not already a Value, so it can still be traced."""
    return Value(x, currency, unit, "current", "calculated", formula=formula)


def when(ts: str | None) -> str:
    """'2026-10-30T20:00:01+00:00' -> '30 Oct 2026, 20:00 UTC'; plain dates -> '30 Oct 2026'; else unchanged."""
    from datetime import datetime
    if not ts:
        return "–"
    try:
        d = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return str(ts)
    if len(str(ts)) <= 10:
        return f"{d.day} {d:%b %Y}"
    return f"{d.day} {d:%b %Y, %H:%M}" + (" UTC" if d.utcoffset() is not None and not d.utcoffset() else "")
