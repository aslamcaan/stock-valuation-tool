"""Compare mode (pure): one ranked table across saved reports. Every figure is the one in its own report; a missing
figure stays None and prints as a dash. Sorted by the probability-weighted expected return (DCF at 25/50/25), with
the blended fair value's upside used only for companies without a DCF (banks, insurers, REITs), marked as such."""
from __future__ import annotations

import csv
import io

from engine.expectations import risk_reward
from engine.report_mc import mc_for

COLUMNS = [  # key, header, kind
    ("ticker", "Ticker", "text"), ("price", "Price (US$)", "money"), ("price_date", "Price date", "text"),
    ("bear", "DCF bear", "money"), ("base", "DCF base", "money"), ("bull", "DCF bull", "money"),
    ("pct_base", "% to base", "pct"), ("pct_bull", "% to bull", "pct"), ("mc_above", "Monte Carlo % above price", "pct0"),
    ("fwd_pe", "Forward P/E", "x"), ("ttm_pe", "Trailing P/E", "x"), ("pe_median", "Own median P/E", "x"),
    ("pe_vs_median", "Trailing vs median", "pct"), ("stage", "Stage", "text"), ("confidence", "Confidence", "text"),
    ("flags", "Flags", "int"), ("expected_return", "Expected return", "pct"), ("basis", "Return basis", "text"),
]


def _pe_vs_own_median(m) -> tuple[float | None, float | None, int]:
    h = (getattr(m, "history", None) or {}).get("pe_trailing")
    if h is None:
        return None, None, 0
    return h.current, h.median, len(h.series or {})


def row_for(rep) -> dict:
    m = rep.model
    v, vd = getattr(m, "valuation", None), m.verdict
    price = vd.price
    fin = getattr(m, "financial", None)
    row = {k: None for k, _, _ in COLUMNS}
    row.update(ticker=rep.ticker, price=price, price_date=str(m.inputs.price.period)[:10],
               stage=(fin.toolkit.capitalize() if fin is not None else v.classification.stage_label),
               confidence=vd.confidence,
               flags=sum(1 for f in m.flags if f.level in ("hard_stop", "red", "amber")))
    rr = None if fin is not None else risk_reward(rep)
    if rr:
        row.update(bear=rr["values"]["bear"], base=rr["values"]["base"], bull=rr["values"]["bull"],
                   pct_base=rr["pct"]["base"], pct_bull=rr["pct"]["bull"], mc_above=rr["prob_above_price"],
                   expected_return=rr["expected_return"], basis="DCF, 25/50/25")
        if rr["fit_failed"]:  # a DCF the report itself rejects is not ranked: it goes last
            row["basis"] = "DCF failed its fit check (not ranked)"
            row["expected_return"] = None
    elif vd.fair_value and price:
        row.update(expected_return=vd.fair_value / price - 1, basis="blended fair value (no DCF)")
    cm = getattr(m, "company_metrics", None)
    if cm is not None and cm.forward_eps and cm.forward_eps > 0 and price:
        row["fwd_pe"] = price / cm.forward_eps
    cur, med, n = _pe_vs_own_median(m)
    row.update(ttm_pe=cur, pe_median=med)
    if cur and med:
        row["pe_vs_median"] = cur / med - 1
    return row


def ranked(reps: list) -> list[dict]:
    rows = [row_for(r) for r in reps]
    rows.sort(key=lambda r: (r["expected_return"] is None, -(r["expected_return"] or 0)))
    for i, r in enumerate(rows, 1):
        r["rank"] = i
    return rows


def fmt(value, kind: str) -> str:
    if value is None:
        return "–"
    if kind == "money":
        return f"{value:,.2f}"
    if kind == "pct":
        return f"{value:+.0%}"
    if kind == "pct0":
        return f"{value:.0%}"
    if kind == "x":
        return f"{value:.1f}x"
    return str(value)


def to_csv(rows: list[dict]) -> str:
    """Raw numbers (not formatted), so the file opens in a spreadsheet and sorts."""
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Rank"] + [h for _, h, _ in COLUMNS])
    for r in rows:
        w.writerow([r["rank"]] + ["" if r[k] is None else (round(r[k], 4) if isinstance(r[k], float) else r[k])
                                  for k, _, _ in COLUMNS])
    return buf.getvalue()
