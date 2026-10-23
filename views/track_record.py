"""Track Record: every completed report, its return since the call vs the S&P 500 and its sector ETF, hit rates."""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import streamlit as st

from engine.history_multiples import price_on_or_before
from engine.track import HORIZONS, evaluate, hit_rates
from ui.state import get_services

svc = get_services()
st.title("Track Record")
calls = svc.store.calls()
if not calls:
    st.info("No completed reports yet. Every report that reaches a verdict is logged here automatically.")
    st.stop()

c1, c2, c3 = st.columns(3)
tickers = c1.multiselect("Ticker", sorted({c["ticker"] for c in calls}))
ratings = c2.multiselect("Rating", ["Strong Buy", "Buy", "Hold", "Sell", "Strong Sell"])
since = c3.date_input("Calls since", value=min(date.fromisoformat(c["call_date"]) for c in calls))
calls = [c for c in calls if (not tickers or c["ticker"] in tickers) and (not ratings or c["rating"] in ratings)
         and date.fromisoformat(c["call_date"]) >= since]

_series: dict[str, dict] = {}


def price_at(ticker: str, when: date) -> float | None:
    if ticker not in _series:
        start = (min(date.fromisoformat(c["call_date"]) for c in calls) - timedelta(days=10)).isoformat()
        r = svc.market.price_history(ticker, start)
        _series[ticker] = {x["date"]: x["close"] for x in r.data} if r.available else {}
    return price_on_or_before(_series[ticker], when, max_gap_days=7)


today = date.today()
with st.spinner("Fetching prices…"):
    results = [evaluate(c, price_at, today) for c in calls]


def p(x):
    return "–" if x is None else f"{x:+.1%}"


rows = [{"Ticker": r.call["ticker"], "Date": r.call["call_date"], "Time": r.call["call_time"],
         "Price at call": r.call["price"], "Fair value": r.call["fair_value"], "Verdict": r.call["verdict"],
         "Rating": r.call["rating"] or "–", "Conviction": r.call["conviction"] or "–",
         "Confidence": r.call["confidence"], "Toolkit": r.call["toolkit"], "Stage": r.call["stage"],
         "Price now": r.price_now, "Return": p(r.ret), "S&P 500": p(r.spy_ret),
         f"Sector ETF": f"{p(r.sector_ret)} ({r.call['sector_etf']})",
         "Moved toward fair value": {True: "yes", False: "no", None: "–"}[r.toward_fair_value]} for r in results]
st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")

st.subheader("Hit rate by rating")
hr = hit_rates(results)
table = []
for group, by_h in hr.items():
    row = {"Rating": group}
    for h in HORIZONS:
        x = by_h[h]
        row[h] = "–" if not x["calls"] else (f"{x['hit_rate']:.0%} of {x['calls']}" if x["hit_rate"] is not None
                                             else f"{x['calls']} calls, avg {x['average_excess']:+.1%}")
    table.append(row)
st.dataframe(pd.DataFrame(table), hide_index=True)
st.caption("A Buy is a hit if it beat the S&P 500 over the horizon; a Sell is a hit if it lagged. Horizons appear as "
           "calls age. Storage is local SQLite; the deployed version will use a hosted database (Phase 16).")
toward = [r.toward_fair_value for r in results if r.toward_fair_value is not None]
if toward:
    st.markdown(f"Price moved toward the fair value in **{sum(toward)} of {len(toward)}** calls.")
