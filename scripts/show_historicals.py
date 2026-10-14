"""Print standardised historicals from a recorded fixture: python scripts/show_historicals.py UBER [line,line]"""
import gzip
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from data_desk.tags import LINES  # noqa: E402
from data_desk.xbrl import extract  # noqa: E402

t = sys.argv[1]
d = json.load(gzip.open(f"tests/fixtures/edgar/{t}.json.gz", "rt"))
h = extract(d["companyfacts"], d["fetched_at"])
print(t, h.currency, h.taxonomy, [p.label for p in h.periods], h.latest_annual_filing)
print("notes:", h.notes, "| dei:", h.dei_shares and h.dei_shares.value, "| convertible:", h.convertible_evidence[:1])
labels = [p.label for p in h.periods][-5:]
for name in (sys.argv[2].split(",") if len(sys.argv) > 2 else LINES):
    row = [h.v(name, lab) for lab in labels]
    tags = {h.get(name, lab).tag for lab in labels if h.get(name, lab)}
    cells = "".join(f"{x:>11,.1f}" if x is not None else f"{'-':>11}" for x in row)
    short = " | ".join(sorted(x.replace("us-gaap:", "").replace("ifrs-full:", "")[:70] for x in tags if x))
    print(f"{name:<30}{cells}   {short}")
