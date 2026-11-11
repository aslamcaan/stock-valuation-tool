"""Store: consensus snapshots (for estimate revisions), the track record and saved reports.

FMP publishes current consensus only, so the tool saves a dated snapshot on every run and measures
30/60/90-day revisions against its own history. SQLite locally, Postgres when deployed (core/db.py).
"""
from __future__ import annotations

import pickle
import zlib
from datetime import date, timedelta
from pathlib import Path

from core.db import Database, as_database

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
TRACK_SCHEMA = """
CREATE TABLE IF NOT EXISTS track_record (
    report_id TEXT PRIMARY KEY,
    ticker TEXT NOT NULL,
    call_date TEXT NOT NULL,
    call_time TEXT NOT NULL,
    price REAL,
    fair_value REAL,
    verdict TEXT,
    rating TEXT,
    conviction TEXT,
    confidence TEXT,
    toolkit TEXT,
    stage TEXT,
    sector_etf TEXT
);
"""
REPORTS_SCHEMA = """
CREATE TABLE IF NOT EXISTS reports (
    report_id TEXT PRIMARY KEY,
    ticker TEXT NOT NULL,
    created_at TEXT NOT NULL,
    headline TEXT,
    payload {BLOB} NOT NULL
);
"""
HOLDINGS_SCHEMA = """
CREATE TABLE IF NOT EXISTS holdings (
    ticker TEXT PRIMARY KEY,
    position_gbp REAL,
    entry_price REAL,
    portfolio_gbp REAL,
    thesis TEXT,
    conditions TEXT,
    updated_at TEXT
);
CREATE TABLE IF NOT EXISTS condition_checks (
    ticker TEXT NOT NULL,
    checked_at TEXT NOT NULL,
    report_id TEXT,
    results TEXT,
    PRIMARY KEY (ticker, checked_at)
);
"""
REVISION_WINDOWS = (30, 60, 90)
WINDOW_SLACK_DAYS = 10  # a snapshot up to this many days older than the target date still counts


class Store:
    def __init__(self, target: Database | str | Path):
        self.db = as_database(target)
        self.db.script(SCHEMA + TRACK_SCHEMA + REPORTS_SCHEMA + HOLDINGS_SCHEMA)

    # --- holdings: the user's own position, thesis and exit conditions (one row per ticker) ---------------------------
    def save_holding(self, ticker: str, **fields) -> None:
        import json
        from datetime import datetime, timezone
        row = {"ticker": ticker.upper(), "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        for k in ("position_gbp", "entry_price", "portfolio_gbp", "thesis"):
            row[k] = fields.get(k)
        row["conditions"] = json.dumps(list(fields.get("conditions") or []))
        self.db.upsert("holdings", row, keys=("ticker",))

    def holding(self, ticker: str) -> dict | None:
        import json
        rows = self.db.query("SELECT * FROM holdings WHERE ticker=?", (ticker.upper(),))
        if not rows:
            return None
        r = rows[0]
        r["conditions"] = json.loads(r.get("conditions") or "[]")
        return r

    def save_checks(self, ticker: str, checked_at: str, report_id: str, results: list[dict]) -> None:
        import json
        self.db.upsert("condition_checks", {"ticker": ticker.upper(), "checked_at": checked_at, "report_id": report_id,
                                            "results": json.dumps(results)}, keys=("ticker", "checked_at"))

    def last_checks(self, ticker: str) -> dict | None:
        import json
        rows = self.db.query("SELECT * FROM condition_checks WHERE ticker=? ORDER BY checked_at DESC LIMIT 1",
                             (ticker.upper(),))
        if not rows:
            return None
        rows[0]["results"] = json.loads(rows[0]["results"] or "[]")
        return rows[0]

    def save_snapshot(self, ticker: str, rows: list[dict], when: date) -> None:
        """rows: {fiscal_year_end, revenue_avg, eps_avg, analysts, source}. One snapshot per ticker per day."""
        for r in rows:
            self.db.upsert("estimate_snapshots", {
                "ticker": ticker.upper(), "snapshot_date": when.isoformat(), "fiscal_year_end": r["fiscal_year_end"],
                "revenue_avg": r.get("revenue_avg"), "eps_avg": r.get("eps_avg"), "analysts": r.get("analysts"),
                "source": r.get("source")}, keys=("ticker", "snapshot_date", "fiscal_year_end"))

    def snapshot_on_or_before(self, ticker: str, target: date) -> tuple[str, dict[str, dict]] | None:
        lo = (target - timedelta(days=WINDOW_SLACK_DAYS)).isoformat()
        latest = self.db.scalar("SELECT MAX(snapshot_date) FROM estimate_snapshots WHERE ticker=? AND snapshot_date<=? "
                                "AND snapshot_date>=?", (ticker.upper(), target.isoformat(), lo))
        if not latest:
            return None
        rows = self.db.query("SELECT fiscal_year_end, revenue_avg, eps_avg, analysts FROM estimate_snapshots "
                             "WHERE ticker=? AND snapshot_date=?", (ticker.upper(), latest))
        return latest, {r["fiscal_year_end"]: {"revenue_avg": r["revenue_avg"], "eps_avg": r["eps_avg"],
                                               "analysts": r["analysts"]} for r in rows}

    def log_call(self, row: dict) -> None:
        cols = ("report_id", "ticker", "call_date", "call_time", "price", "fair_value", "verdict", "rating",
                "conviction", "confidence", "toolkit", "stage", "sector_etf")
        self.db.upsert("track_record", {k: row.get(k) for k in cols}, keys=("report_id",))

    def calls(self) -> list[dict]:
        return self.db.query("SELECT * FROM track_record ORDER BY call_date DESC, call_time DESC")

    # --- saved reports (pickled FullReport objects, compressed) -----------------------------------------------------
    def save_report(self, report_id: str, ticker: str, created_at: str, headline: str, obj) -> None:
        payload = zlib.compress(pickle.dumps(obj, protocol=pickle.HIGHEST_PROTOCOL), 6)
        self.db.upsert("reports", {"report_id": report_id, "ticker": ticker, "created_at": created_at,
                                   "headline": headline, "payload": payload}, keys=("report_id",))

    def load_report(self, report_id: str):
        rows = self.db.query("SELECT payload FROM reports WHERE report_id=?", (report_id,))
        if not rows:
            raise KeyError(f"No saved report {report_id}")
        return pickle.loads(zlib.decompress(bytes(rows[0]["payload"])))

    def recent_reports(self, limit: int = 12) -> list[dict]:
        return self.db.query("SELECT report_id, ticker, created_at, headline FROM reports "
                             "ORDER BY created_at DESC LIMIT ?", (limit,))

    def revisions(self, ticker: str, today: date, current: list[dict]) -> dict:
        """For each window, % change in revenue and EPS consensus per fiscal year since the snapshot."""
        out = {}
        for days in REVISION_WINDOWS:
            snap = self.snapshot_on_or_before(ticker, today - timedelta(days=days))
            if snap is None:
                out[days] = {"available": False, "reason": f"no saved consensus from about {days} days ago yet"}
                continue
            snap_date, old = snap
            changes = {}  # nearest fiscal year first (FMP lists the furthest first); only years not yet ended
            for r in sorted(current, key=lambda r: r["fiscal_year_end"]):
                if r["fiscal_year_end"] <= today.isoformat():
                    continue
                o = old.get(r["fiscal_year_end"])
                if not o:
                    continue
                changes[r["fiscal_year_end"]] = {
                    "revenue": (r["revenue_avg"] / o["revenue_avg"] - 1) if r.get("revenue_avg") and o["revenue_avg"] else None,
                    "eps": (r["eps_avg"] / o["eps_avg"] - 1) if r.get("eps_avg") and o["eps_avg"] and o["eps_avg"] > 0 else None,
                }
            out[days] = {"available": bool(changes), "snapshot_date": snap_date, "changes": changes}
        return out
