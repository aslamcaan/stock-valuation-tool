"""SPDR sector ETF for a SIC code (benchmark for the track record)."""
from __future__ import annotations

RANGES = [
    ((1000, 1499), "XLB"), ((1300, 1399), "XLE"), ((2900, 2999), "XLE"), ((2000, 2199), "XLP"), ((2800, 2829), "XLB"),
    ((2830, 2836), "XLV"), ((2840, 2899), "XLB"), ((3570, 3579), "XLK"), ((3600, 3699), "XLK"), ((3710, 3716), "XLY"),
    ((3800, 3851), "XLV"), ((4000, 4799), "XLI"), ((4800, 4899), "XLC"), ((4900, 4999), "XLU"), ((5000, 5199), "XLI"),
    ((5200, 5999), "XLY"), ((6000, 6411), "XLF"), ((6500, 6799), "XLRE"), ((7370, 7379), "XLK"), ((7800, 7999), "XLC"),
    ((8000, 8099), "XLV"),
]


def sector_etf(sic: str) -> str:
    try:
        code = int(sic)
    except (TypeError, ValueError):
        return "SPY"
    best = None
    for (lo, hi), etf in RANGES:
        if lo <= code <= hi and (best is None or hi - lo < best[0]):
            best = (hi - lo, etf)
    return best[1] if best else "XLI"
