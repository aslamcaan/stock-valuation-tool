"""Date helpers that are safe on 29 February."""
from __future__ import annotations

from datetime import date


def years_earlier(d: date, years: int = 1) -> date:
    """Same calendar day `years` earlier; 29 Feb maps to 28 Feb in a non-leap year."""
    try:
        return d.replace(year=d.year - years)
    except ValueError:
        return d.replace(year=d.year - years, day=28)


def has(v) -> bool:
    """True when a Value-like object exists and carries a number (0.0 counts as present)."""
    return v is not None and getattr(v, "value", None) is not None
