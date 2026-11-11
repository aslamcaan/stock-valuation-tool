"""Cyclical price deck (pure). A price index summarised as a level, its 3- and 12-month change and where it sits in its own
ten-year range. For the memory and storage names it moves the mid-cycle margin target within the company's own range:
when prices sit high in their range the target is nearer the 90th-percentile margin, when low nearer the median. The
default (no deck) is half way, as before. The series is whatever the data layer supplies, and the report names it."""
from __future__ import annotations

TREND_BAND = 0.02  # a 12-month change within +/-2% reads as flat (producer price indices move slowly)


def summarise(obs: list[tuple[str, float | None]], years: int = 10) -> dict | None:
    """`obs`: [(YYYY-MM-DD, value)] in any order, monthly. None if under 24 usable months."""
    pts = sorted((d, v) for d, v in obs if v is not None)
    if len(pts) < 24:
        return None
    last_d, last = pts[-1]
    window = [v for _, v in pts[-12 * years:]]

    def back(n: int) -> float | None:
        return pts[-1 - n][1] if len(pts) > n else None
    m3, m12 = back(3), back(12)
    ch3 = last / m3 - 1 if m3 else None
    ch12 = last / m12 - 1 if m12 else None
    below = sum(1 for v in window if v < last)
    equal = sum(1 for v in window if v == last)
    position = (below + 0.5 * equal) / len(window)
    trend = None if ch12 is None else "rising" if ch12 > TREND_BAND else "falling" if ch12 < -TREND_BAND else "flat"
    return {"as_of": last_d, "latest": last, "change_3m": ch3, "change_12m": ch12, "trend": trend,
            "position": position, "months": len(window), "low": min(window), "high": max(window)}


def target_margin(median: float, p90: float, position: float | None) -> float:
    """Mid-cycle margin target: the median plus `position` of the way to the 90th percentile (0.5 without a deck)."""
    w = 0.5 if position is None else min(max(position, 0.0), 1.0)
    return median + w * max(p90 - median, 0.0)
