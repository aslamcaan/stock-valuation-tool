"""Company search over SEC company_tickers_exchange.json rows."""
from __future__ import annotations

US_EXCHANGES = {"NYSE", "Nasdaq", "NYSE American", "NYSE Arca", "CBOE", "BATS"}


def search(rows: list[dict], query: str, limit: int = 10) -> list[dict]:
    """Rank listed companies by match quality against a ticker or name fragment.

    Order: exact ticker, ticker prefix, name prefix, name word prefix, name substring.
    Only rows on a US exchange are returned (OTC and unlisted rows are dropped).
    """
    q = query.strip().upper()
    if not q:
        return []
    scored = []
    for r in rows:
        if r.get("exchange") not in US_EXCHANGES:
            continue
        ticker = str(r["ticker"]).upper()
        name = str(r["name"]).upper()
        if ticker == q:
            score = 0
        elif ticker.startswith(q):
            score = 1
        elif name.startswith(q):
            score = 2
        elif any(w.startswith(q) for w in name.replace(",", " ").replace(".", " ").split()):
            score = 3
        elif q in name:
            score = 4
        else:
            continue
        scored.append((score, len(ticker), ticker, r))
    scored.sort(key=lambda x: x[:3])
    seen, out = set(), []
    for *_, r in scored:
        if r["ticker"] in seen:
            continue
        seen.add(r["ticker"])
        out.append(r)
        if len(out) == limit:
            break
    return out


def label(row: dict) -> str:
    return f"{row['name']} ({row['ticker']}) · {row['exchange']}"
