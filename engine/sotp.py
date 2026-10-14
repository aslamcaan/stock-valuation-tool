"""Sum-of-the-parts (pure). Each segment is valued on its own metric and multiple (or its own DCF value)."""
from __future__ import annotations

from dataclasses import dataclass

MATERIAL_MARGIN_GAP = 0.10   # segments' margins differ by more than 10 points
MATERIAL_GROWTH_GAP = 0.10   # or their growth rates by more than 10 points
MIN_SEGMENT_SHARE = 0.10     # each compared segment is at least 10% of revenue


@dataclass(frozen=True)
class Segment:
    name: str
    revenue: float
    profit: float | None = None          # segment operating profit or adjusted EBITDA
    growth: float | None = None
    metric: str = "EV/Sales"             # which multiple is applied
    metric_value: float | None = None    # the base the multiple is applied to
    multiple: float | None = None
    multiple_source: str = ""
    dcf_value: float | None = None       # alternatively, a segment DCF enterprise value


@dataclass(frozen=True)
class SOTPResult:
    applicable: bool
    reason: str
    segment_values: tuple[tuple[str, float, str], ...] = ()  # (name, EV, how)
    enterprise_value: float | None = None
    equity_value: float | None = None
    value_per_share: float | None = None


def applicability(segments: list[Segment]) -> tuple[bool, str]:
    total = sum(s.revenue for s in segments)
    big = [s for s in segments if total and s.revenue / total >= MIN_SEGMENT_SHARE]
    if len(big) < 2:
        return False, "fewer than two segments with at least 10% of revenue"
    margins = [s.profit / s.revenue for s in big if s.profit is not None and s.revenue]
    growths = [s.growth for s in big if s.growth is not None]
    if len(margins) >= 2 and max(margins) - min(margins) > MATERIAL_MARGIN_GAP:
        return True, f"segment margins range from {min(margins):.1%} to {max(margins):.1%}"
    if len(growths) >= 2 and max(growths) - min(growths) > MATERIAL_GROWTH_GAP:
        return True, f"segment growth ranges from {min(growths):.1%} to {max(growths):.1%}"
    if len(margins) < 2 and len(growths) < 2:
        return False, "segment profit and growth not available"
    return False, "segments have similar economics; the consolidated DCF is sufficient"


def run_sotp(segments: list[Segment], bridge: float, shares: float) -> SOTPResult:
    ok, why = applicability(segments)
    if not ok:
        return SOTPResult(False, why)
    values = []
    for s in segments:
        if s.dcf_value is not None:
            values.append((s.name, s.dcf_value, "segment DCF"))
        elif s.metric_value is not None and s.multiple is not None:
            values.append((s.name, s.metric_value * s.multiple,
                           f"{s.metric} {s.multiple:.1f}x on {s.metric_value:,.0f} ({s.multiple_source})"))
        else:
            return SOTPResult(False, f"no multiple or DCF value for segment {s.name}")
    ev = sum(v for _, v, _ in values)
    eq = ev + bridge
    return SOTPResult(True, why, tuple(values), ev, eq, eq / shares)
