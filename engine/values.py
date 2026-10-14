"""Traceable values: every number carries where it came from.

Sourced values record the filing, tag and fetch time. Calculated values record the formula and
the input values, so the UI can show a full trace (click-to-trace).
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Iterable

# Units
MILLIONS = "m"            # millions of `currency`
PER_SHARE = "per_share"   # currency per share
SHARES_M = "shares_m"     # millions of shares
RATIO = "ratio"           # 0.153 = 15.3%
MULTIPLE = "x"
DAYS = "days"


@dataclass(frozen=True)
class Value:
    value: float | None
    currency: str | None
    unit: str
    period: str
    source: str
    tag: str | None = None
    fetched_at: str | None = None
    filing: str | None = None     # e.g. "10-K filed 2026-02-12 (0001543151-26-000010)"
    formula: str | None = None    # for calculated values
    inputs: tuple["Value", ...] = field(default=(), repr=False)
    input_names: tuple[str, ...] = ()
    note: str | None = None

    @property
    def is_missing(self) -> bool:
        return self.value is None

    def with_note(self, note: str) -> "Value":
        return replace(self, note=f"{self.note}; {note}" if self.note else note)

    def trace(self, depth: int = 0, name: str | None = None) -> list[str]:
        """Human-readable provenance tree."""
        pad = "  " * depth
        label = f"{name}: " if name else ""
        v = "missing" if self.value is None else f"{self.value:,.4g}"
        if self.formula:
            lines = [f"{pad}{label}{v} = {self.formula} [{self.period}]"]
            for n, iv in zip(self.input_names, self.inputs):
                lines += iv.trace(depth + 1, n)
            return lines
        where = ", ".join(x for x in (self.source, self.tag, self.filing,
                                      f"fetched {self.fetched_at}" if self.fetched_at else None) if x)
        return [f"{pad}{label}{v} {self.currency or ''} {self.unit} [{self.period}] ({where})"
                + (f" — {self.note}" if self.note else "")]


def missing(period: str, unit: str, currency: str | None = None, note: str = "not reported") -> Value:
    return Value(None, currency, unit, period, "missing", note=note)


def calc(fn, formula: str, period: str, unit: str, currency: str | None, **inputs: Value) -> Value:
    """Compute fn(*inputs) in keyword order; names label the inputs in the trace.

    Missing input, or a division by zero, gives a missing result.
    """
    vals = {k: v.value for k, v in inputs.items()}
    names = tuple(inputs)
    if any(x is None for x in vals.values()):
        absent = [k for k, x in vals.items() if x is None]
        return Value(None, currency, unit, period, "calculated", formula=formula, inputs=tuple(inputs.values()),
                     input_names=names, note=f"missing input: {', '.join(absent)}")
    try:
        result = fn(*vals.values())
    except ZeroDivisionError:
        result = None
    return Value(result, currency, unit, period, "calculated", formula=formula,
                 inputs=tuple(inputs.values()), input_names=names,
                 note=None if result is not None else "division by zero")


def first_present(values: Iterable[Value]) -> Value | None:
    for v in values:
        if v is not None and v.value is not None:
            return v
    return None
