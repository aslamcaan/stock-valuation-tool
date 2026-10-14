"""Record SEC companyfacts + submissions for golden-test tickers into tests/fixtures/edgar/ (gzipped).

Run: python scripts/record_edgar_fixtures.py [TICKER ...]
"""
from __future__ import annotations

import gzip
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.services import build_services  # noqa: E402

OUT = ROOT / "tests" / "fixtures" / "edgar"
DEFAULT = ["GRAB", "UBER", "AAPL", "KO", "ASML", "MU", "JPM", "O", "TRV", "CVX"]


def record(tickers: list[str]) -> None:
    svc = build_services()
    OUT.mkdir(parents=True, exist_ok=True)
    rows = svc.edgar.company_tickers()
    for t in tickers:
        cik = svc.edgar.cik_for(t)
        facts = svc.edgar.companyfacts(cik)
        subs = svc.edgar.submissions(cik)
        payload = {"ticker": t, "cik": cik, "fetched_at": facts.fetched_at_iso,
                   "companyfacts": facts.payload, "submissions": subs.payload,
                   "tickers_row": next(r for r in rows.payload if r["ticker"] == t)}
        with gzip.open(OUT / f"{t}.json.gz", "wt", encoding="utf-8") as fh:
            json.dump(payload, fh)
        print(t, cik, (OUT / f"{t}.json.gz").stat().st_size // 1024, "KB")


if __name__ == "__main__":
    record(sys.argv[1:] or DEFAULT)
