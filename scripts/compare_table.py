"""Ranked compare table from the latest saved report of each ticker. usage: compare_table.py OUT_PREFIX T1 T2 ...
Writes OUT_PREFIX.csv and OUT_PREFIX.pdf and prints the table."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.services import build_services  # noqa: E402
from desks.pipeline import load  # noqa: E402
from engine.compare_table import COLUMNS, fmt, ranked, to_csv  # noqa: E402
from exports.compare_pdf import build_compare_pdf  # noqa: E402

prefix, tickers = sys.argv[1], [t.upper() for t in sys.argv[2:]]
svc = build_services()
latest = {}
for r in svc.store.recent_reports(500):
    latest.setdefault(r["ticker"], r["report_id"])
reps = []
for t in tickers:
    if t not in latest:
        print(f"{t}: no saved report, skipped")
        continue
    rep = load(latest[t], svc.store)
    if rep.model is not None:
        reps.append(rep)
rows = ranked(reps)
Path(prefix + ".csv").write_text(to_csv(rows), encoding="utf-8")
Path(prefix + ".pdf").write_bytes(build_compare_pdf(rows))
for r in rows:
    print(r["rank"], " | ".join(f"{h}: {fmt(r[k], kind)}" for k, h, kind in COLUMNS))
