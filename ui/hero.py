"""The landing hero's chart: the newest report's last year of daily closes against its fair value and DCF range.

Drawn from data the report already fetched (read from the cache, never the network), so the landing page stays
instant; when no saved report has a cached price series, the page falls back to a decorative line.
"""
from __future__ import annotations

W, H, TOP, BOTTOM = 800, 300, 40, 280
RIGHT = W - 14  # the last close's dot (and its halo) stays inside the chart


def _y(v: float, lo: float, hi: float) -> float:
    return BOTTOM - (v - lo) / (hi - lo) * (BOTTOM - TOP)


def hero_svg(closes: list[tuple[str, float]], fair_value: float, band: tuple[float, float] | None = None,
             step: int = 3) -> str:
    """SVG of `closes` (ascending (date, close)) with the fair value as a dashed line and `band` (DCF bear to bull)
    as a shaded range. The classes match the hero's draw-in animation in ui/theme.py."""
    pts = closes[::step]
    if closes and pts[-1] != closes[-1]:
        pts.append(closes[-1])  # always end on the latest close
    values = [c for _, c in pts] + [fair_value] + (list(band) if band else [])
    lo, hi = min(values), max(values)
    pad = (hi - lo) * 0.08 or 1.0
    lo, hi = lo - pad, hi + pad
    n = len(pts) - 1 or 1
    xy = [(i / n * RIGHT, _y(c, lo, hi)) for i, (_, c) in enumerate(pts)]
    line = " ".join(f"{'M' if i == 0 else 'L'}{x:.1f} {y:.1f}" for i, (x, y) in enumerate(xy))
    fy = _y(fair_value, lo, hi)
    shade = ""
    if band:
        top, bot = _y(max(band), lo, hi), _y(min(band), lo, hi)
        # a faint range with hairline edges, so it reads as a band rather than a block behind the line
        shade = (f"<rect class='fvl' x='0' y='{top:.1f}' width='{W}' height='{bot - top:.1f}' fill='rgba(255,122,26,.035)'/>"
                 + "".join(f"<line class='fvl' x1='0' y1='{y:.1f}' x2='{W}' y2='{y:.1f}' stroke='#ff7a1a' "
                           "stroke-opacity='.16' stroke-width='1'/>" for y in (top, bot)))
    lx, ly = xy[-1]
    return (f"<svg class='chart' viewBox='0 0 {W} {H}' preserveAspectRatio='none' aria-hidden='true'>"
            "<defs><linearGradient id='vtg' x1='0' y1='0' x2='0' y2='1'><stop offset='0' stop-color='#ff7a1a' "
            "stop-opacity='.2'/><stop offset='.85' stop-color='#ff7a1a' stop-opacity='0'/></linearGradient></defs>"
            f"{shade}<line class='fvl fv' x1='0' y1='{fy:.1f}' x2='{W}' y2='{fy:.1f}' stroke='#ff7a1a' "
            "stroke-opacity='.55' stroke-dasharray='4 6'/>"
            f"<path class='area' d='{line} L{lx:.1f} {H} L0 {H} Z' fill='url(#vtg)'/>"
            f"<path class='line' d='{line}' pathLength='1600' fill='none' stroke='#ff7a1a' stroke-width='2.5' stroke-linejoin='round'/>"
            f"<circle class='halo' cx='{lx:.1f}' cy='{ly:.1f}' r='6' fill='#ff7a1a'/>"
            f"<circle class='dot' cx='{lx:.1f}' cy='{ly:.1f}' r='5' fill='#ffd2ad'/></svg>")
