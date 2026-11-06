"""ADR ratios: ordinary shares represented by one US-traded share (ADS).

There is no structured source for these, so known ratios are listed here and every value is
cross-checked against market capitalisation (`implied_ratio`). A mismatch raises an amber flag.
Companies whose ordinary shares trade directly in the US (e.g. GRAB, ASML New York shares) are 1.
"""
from __future__ import annotations

ADR_RATIOS: dict[str, float] = {
    "TSM": 5, "BABA": 8, "BIDU": 8, "JD": 2, "PDD": 4, "NTES": 5, "HDB": 3, "IBN": 2, "BP": 6, "SHEL": 2,
    "AZN": 0.5, "GSK": 2, "TM": 10, "HSBC": 5, "BHP": 2,
    "JMIA": 2,  # each Jumia ADS represents two ordinary shares (SEC Schedule 13G, 2025)
}


ASSUMED_NOTE = "assumed 1:1 (no ADR ratio on file)"


def adr_ratio(ticker: str) -> tuple[float, str]:
    t = ticker.upper()
    if t in ADR_RATIOS:
        return ADR_RATIOS[t], "ADR ratio table (data_desk/adr.py)"
    return 1.0, ASSUMED_NOTE


def on_file(ticker: str) -> bool:
    return ticker.upper() in ADR_RATIOS


def is_foreign_private_issuer(sub: dict | None) -> bool:
    """True when the newest annual or quarterly report is a 20-F or 40-F: the company may trade in the US as ADSs."""
    recent = ((sub or {}).get("filings") or {}).get("recent") or {}
    for form in recent.get("form", []):  # newest first
        if form in ("10-K", "10-Q", "20-F", "40-F"):
            return form in ("20-F", "40-F")
    return False


def implied_ratio(ordinary_shares_m: float, price: float, market_cap_m: float) -> float | None:
    """Ordinary shares per US share implied by price x shares vs a provider's market cap."""
    if not (ordinary_shares_m and price and market_cap_m):
        return None
    return ordinary_shares_m * price / market_cap_m
