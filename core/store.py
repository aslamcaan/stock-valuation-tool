"""Local SQLite store: consensus snapshots (for estimate revisions) and, later, the track record.

FMP publishes current consensus only, so the tool saves a dated snapshot on every run and measures
30/60/90-day revisions against its own history.
"""
from __future__ import annotations

import sqlite3
import threading
from datetime import date, timedelta
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS estimate_snapshots (
    ticker TEXT NOT NULL,
    snapshot_date TEXT NOT NULL,
    fiscal_year_end TEXT NOT NULL,
    revenue_avg REAL,
    eps_avg REAL,
    analysts INTEGER,
    source TEXT,
    PRIMARY KEY (ticker, snapshot_date, fiscal_year_end)
);
"""
REVISION_WINDOWS = (30, 60, 90)
WINDOW_SLACK_DAYS = 10  # a snapshot up to this many days older than the target date still counts


class Store:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        with self._conn() as c:
            c.executescript(SCHEMA)

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path)

    def save_snapshot(self, ticker: str, rows: list[dict], when: date) -> None:
        """rows: {fiscal_year_end, revenue_avg, eps_avg, analysts, source}. One snapshot per ticker per day."""
        with self._lock, self._conn() as c:
            for r in rows:
                c.execute("INSERT OR REPLACE INTO estimate_snapshots VALUES (?,?,?,?,?,?,?)",
                          (ticker.upper(), when.isoformat(), r["fiscal_year_end"], r.get("revenue_avg"),
                           r.get("eps_avg"), r.get("analysts"), r.get("source")))

    def snapshot_on_or_before(self, ticker: str, target: date) -> tuple[str, dict[str, dict]] | None:
        lo = (target - timedelta(days=WINDOW_SLACK_DAYS)).isoformat()
        with self._conn() as c:
            row = c.execute("SELECT MAX(snapshot_date) FROM estimate_snapshots WHERE ticker=? AND snapshot_date<=? "
                            "AND snapshot_date>=?", (ticker.upper(), target.isoformat(), lo)).fetchone()
            if not row or not row[0]:
                return None
            rows = c.execute("SELECT fiscal_year_end, revenue_avg, eps_avg, analysts FROM estimate_snapshots "
                             "WHERE ticker=? AND snapshot_date=?", (ticker.upper(), row[0])).fetchall()
        return row[0], {r[0]: {"revenue_avg": r[1], "eps_avg": r[2], "analysts": r[3]} for r in rows}

    def revisions(self, ticker: str, today: date, current: list[dict]) -> dict:
        """For each window, % change in revenue and EPS consensus per fiscal year since the snapshot."""
        out = {}
        for days in REVISION_WINDOWS:
            snap = self.snapshot_on_or_before(ticker, today - timedelta(days=days))
            if snap is None:
                out[days] = {"available": False, "reason": f"no saved consensus from about {days} days ago yet"}
                continue
            snap_date, old = snap
            changes = {}
            for r in current:
                o = old.get(r["fiscal_year_end"])
                if not o:
                    continue
                changes[r["fiscal_year_end"]] = {
                    "revenue": (r["revenue_avg"] / o["revenue_avg"] - 1) if r.get("revenue_avg") and o["revenue_avg"] else None,
                    "eps": (r["eps_avg"] / o["eps_avg"] - 1) if r.get("eps_avg") and o["eps_avg"] and o["eps_avg"] > 0 else None,
                }
            out[days] = {"available": bool(changes), "snapshot_date": snap_date, "changes": changes}
        return out
