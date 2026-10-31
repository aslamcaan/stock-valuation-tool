"""Track Record: every completed report, its return since the call vs the S&P 500 and its sector ETF, hit rates."""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import streamlit as st

from engine.history_multiples import price_on_or_before
from engine.track import HORIZONS, evaluate, hit_rates
from ui.format import money, plain_table
from ui.theme import esc, note
from ui.state import get_services

svc = get_services()
st.title("Track Record")
st.caption("Every report that reaches a verdict is logged with its date, price and fair value. Returns are measured "
           "from the call against the S&P 500 and the company's sector ETF.")
calls = svc.store.calls()
if not calls:
    st.markdown(note("No completed reports yet. Every report that reaches a verdict is logged here automatically."),
                unsafe_allow_html=True)
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
         "Price at call": money(r.call["price"]), "Fair value": money(r.call["fair_value"]), "Verdict": r.call["verdict"],
         "Rating": r.call["rating"] or "–", "Conviction": r.call["conviction"] or "–",
         "Confidence": r.call["confidence"], "Toolkit": r.call["toolkit"], "Stage": (r.call["stage"] or "").replace("_", " "),
         "Price now": money(r.price_now), "Return": p(r.ret), "S&P 500": p(r.spy_ret),
         f"Sector ETF": f"{p(r.sector_ret)} ({r.call['sector_etf']})",
         "Moved toward fair value": {True: "yes", False: "no", None: "–"}[r.toward_fair_value]} for r in results]
rets = [r.ret for r in results if r.ret is not None]
excess = [r.ret - r.spy_ret for r in results if r.ret is not None and r.spy_ret is not None]
toward = [r.toward_fair_value for r in results if r.toward_fair_value is not None]
tiles = [("Calls", f"{len(results)}", f"{len({r.call['ticker'] for r in results})} companies"),
         ("Average return", p(sum(rets) / len(rets)) if rets else "–", "since each call"),
         ("Average vs S&P 500", p(sum(excess) / len(excess)) if excess else "–", "excess return"),
         ("Moved toward fair value", f"{sum(toward)} of {len(toward)}" if toward else "–", "price vs the call's fair value")]
st.markdown("<div class='vt-head' style='padding-top:.2rem'><div class='vt-kpis' style='grid-template-columns:"
            "repeat(4,minmax(0,1fr));border-top:none;margin-top:0'>"
            + "".join(f"<div class='vt-kpi'><div class='l'>{esc(a)}</div><div class='v'>{esc(b)}</div>"
                      f"<div class='s'>{esc(c)}</div></div>" for a, b, c in tiles) + "</div></div>",
            unsafe_allow_html=True)
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
if table:
    st.markdown(plain_table([list(r.values()) for r in table], list(table[0].keys())), unsafe_allow_html=True)
st.caption("A Buy is a hit if it beat the S&P 500 over the horizon; a Sell is a hit if it lagged. Horizons appear as "
           "calls age.")
