"""Flags: hard stops, red, amber and info, each carrying the numbers that triggered it."""
from __future__ import annotations

from dataclasses import dataclass, field

HARD_STOP = "hard_stop"
RED = "red"
AMBER = "amber"
INFO = "info"
SEVERITY_ORDER = {HARD_STOP: 0, RED: 1, AMBER: 2, INFO: 3}


@dataclass(frozen=True)
class Flag:
    level: str
    code: str
    title: str
    message: str  # plain English, shown in the report
    period: str | None = None
    numbers: dict = field(default_factory=dict)  # name -> number that triggered it

    @property
    def is_hard_stop(self) -> bool:
        return self.level == HARD_STOP


def sort_flags(flags: list[Flag]) -> list[Flag]:
    return sorted(flags, key=lambda f: (SEVERITY_ORDER[f.level], f.code, f.period or ""))


def rel_diff(a: float, b: float) -> float:
    """|a - b| relative to the larger magnitude (0 when both are 0)."""
    m = max(abs(a), abs(b))
    return 0.0 if m == 0 else abs(a - b) / m
