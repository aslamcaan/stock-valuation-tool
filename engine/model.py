"""Core data types shared by the data desk and the engine (pure, no I/O)."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from engine.values import Value


@dataclass(frozen=True)
class Period:
    label: str
    end: date
    start: date | None
    kind: str  # "FY" or "LTM"
    ytd_start: date | None = None  # LTM only
    ytd_months: int | None = None
    source: str = "EDGAR"  # "FMP" when an LTM had to be built from FMP quarterly statements


@dataclass
class Historicals:
    """Standardised line items by period, in the reporting currency."""
    currency: str
    taxonomy: str
    periods: list[Period]                       # FY periods ascending, then LTM if built
    lines: dict[str, dict[str, Value]]          # line -> period label -> Value
    tag_log: list[dict] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    latest_annual_filing: dict | None = None    # {form, filed, accn, end}
    dei_shares: Value | None = None
    convertible_evidence: list[str] = field(default_factory=list)

    def get(self, line: str, period: str) -> Value | None:
        return self.lines.get(line, {}).get(period)

    def v(self, line: str, period: str) -> float | None:
        x = self.get(line, period)
        return None if x is None else x.value

    @property
    def fy_labels(self) -> list[str]:
        return [p.label for p in self.periods if p.kind == "FY"]

    @property
    def ltm(self) -> Period | None:
        return next((p for p in self.periods if p.kind == "LTM"), None)
