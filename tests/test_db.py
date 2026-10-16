"""Storage works the same on SQLite (local) and Postgres (deployed).

Postgres runs only when VT_TEST_PG_URL points at a throwaway database, e.g.
VT_TEST_PG_URL=postgresql://user:pass@localhost:5432/postgres pytest tests/test_db.py
"""
from __future__ import annotations

import os
from datetime import date, datetime, timedelta, timezone

import pytest

from core.cache import Cache
from core.db import Database
from core.store import Store
from desks.ai import CallRecord, CostCapExceeded, CostLedger

PG_URL = os.environ.get("VT_TEST_PG_URL")


@pytest.fixture(params=["sqlite", "postgres"])
def db(request, tmp_path):
    if request.param == "sqlite":
        return Database(tmp_path / "t.sqlite")
    if not PG_URL:
        pytest.skip("VT_TEST_PG_URL not set")
    d = Database(PG_URL)
    for t in ("estimate_snapshots", "track_record", "reports", "ai_calls", "cache_entries"):
        d.execute(f"DROP TABLE IF EXISTS {t}")
    return d


def test_snapshots_and_revisions(db):
    s = Store(db)
    today = date(2026, 10, 16)
    s.save_snapshot("ko", [{"fiscal_year_end": "2026-12-31", "revenue_avg": 100.0, "eps_avg": 2.0, "analysts": 20,
                            "source": "FMP"}], today - timedelta(days=31))
    s.save_snapshot("KO", [{"fiscal_year_end": "2026-12-31", "revenue_avg": 101.0, "eps_avg": 2.1, "analysts": 21,
                            "source": "FMP"}], today - timedelta(days=31))  # same day: replaces
    snap = s.snapshot_on_or_before("KO", today - timedelta(days=30))
    assert snap[1]["2026-12-31"]["revenue_avg"] == 101.0
    rev = s.revisions("KO", today, [{"fiscal_year_end": "2026-12-31", "revenue_avg": 111.1, "eps_avg": 2.31}])
    assert rev[30]["changes"]["2026-12-31"]["revenue"] == pytest.approx(0.1)
    assert rev[90]["available"] is False


def test_track_record_upsert(db):
    s = Store(db)
    row = {"report_id": "r1", "ticker": "KO", "call_date": "2026-10-15", "call_time": "10:00", "price": 70.0,
           "fair_value": 50.0, "verdict": "Overvalued", "rating": "Sell"}
    s.log_call(row)
    s.log_call({**row, "rating": "Hold"})
    calls = s.calls()
    assert len(calls) == 1 and calls[0]["rating"] == "Hold" and calls[0]["conviction"] is None


def test_reports_round_trip(db):
    s = Store(db)
    obj = {"ticker": "UBER", "values": list(range(5000)), "when": date(2026, 10, 15)}
    s.save_report("UBER-1", "UBER", "2026-10-15T10:00:00", "Fairly valued", obj)
    s.save_report("KO-1", "KO", "2026-10-16T10:00:00", "Overvalued", {"ticker": "KO"})
    assert s.load_report("UBER-1") == obj
    assert [r["report_id"] for r in s.recent_reports()] == ["KO-1", "UBER-1"]
    with pytest.raises(KeyError):
        s.load_report("missing")


def test_cost_ledger(db):
    led = CostLedger(db, per_report_cap=0.10, per_day_cap=0.15)
    rec = CallRecord(desk="MD", model="m", at=datetime.now(timezone.utc).isoformat(), input_tokens=1, output_tokens=1,
                     cache_read_tokens=0, searches=0, cost=0.08, cached=False, served_by="m")
    led.log("r1", rec)
    assert led.spent_on_report("r1") == pytest.approx(0.08)
    with pytest.raises(CostCapExceeded):
        led.check("r1", 0.05)
    led.log("r2", rec)
    with pytest.raises(CostCapExceeded):  # day cap 0.15 < 0.16
        led.check("r3", 0.0)


def test_ai_cache_in_database(db, tmp_path):
    c = Cache(tmp_path / "files", db=db)
    c.write("ai", "request-1", {"data": {"x": 1}})
    c.write("price", "AAPL", {"p": 1})
    assert c.read("ai", "request-1").payload == {"data": {"x": 1}}
    assert not (tmp_path / "files" / "ai").exists()  # AI entries live in the database
    assert (tmp_path / "files" / "price").exists()   # everything else stays on disk
    fresh = Cache(tmp_path / "other", db=db)          # a restarted app with an empty disk
    assert fresh.read("ai", "request-1").payload == {"data": {"x": 1}}
