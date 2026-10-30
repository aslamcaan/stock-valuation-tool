"""Compare: two saved reports side by side (verdict, rating, key metrics, multiples, football fields).
Uses saved reports only, so it opens instantly at no API cost; every figure is the one in each report."""
from __future__ import annotations

import streamlit as st

from desks.pipeline import load
from ui.format import money
from ui.report import football
from ui.state import get_services

MULTIPLES = [("pe_trailing", "P/E (trailing)"), ("pe_forward", "P/E (forward)"), ("ev_sales", "EV/Sales"),
             ("ev_ebitda", "EV/EBITDA"), ("ev_fcf", "EV/FCF")]
METRICS = [("revenue_growth", "Revenue growth", "pct"), ("operating_margin", "Operating margin", "pct"),
           ("fcf_margin", "FCF margin", "pct"), ("roic", "ROIC", "pct"), ("net_debt_to_ebitda", "Net debt / EBITDA", "x"),
           ("interest_cover", "Interest cover", "x")]

svc = get_services()
st.title("Compare")
st.caption("Two saved reports side by side. Run a report on the Search page first; each figure here is exactly as "
           "computed in its report, with that report's date.")

try:
    rows = svc.store.recent_reports(60)
except Exception as exc:
    st.error(f"Could not load saved reports: {exc}")
    st.stop()
latest: dict[str, dict] = {}
for r in rows:  # newest first: keep the latest report per ticker
    latest.setdefault(r["ticker"], r)
choices = list(latest.values())
if len(choices) < 2:
    st.info("Compare needs saved reports on at least two companies.")
    st.stop()


def label(r: dict) -> str:
    return f"{r['ticker']} · {r['created_at'][:10]} · {r['headline']}"


c1, c2 = st.columns(2)
a = c1.selectbox("First company", choices, index=0, format_func=label)
b = c2.selectbox("Second company", choices, index=1, format_func=label)
if a["report_id"] == b["report_id"]:
    st.warning("Pick two different reports.")
    st.stop()


@st.cache_data(show_spinner="Opening saved reports…", max_entries=8)
def _load(report_id: str):
    return load(report_id, get_services().store)


reps = [_load(a["report_id"]), _load(b["report_id"])]
if any(r.model is None for r in reps):
    st.warning("One of these reports stopped before a valuation; pick another.")
    st.stop()


def fmt(x, kind):
    if x is None:
        return "n/a"
    return f"{x:.1%}" if kind == "pct" else f"{x:.2f}x" if kind == "x" else money(x)


def latest_period(rep) -> str:
    h = rep.company.historicals_usd
    return h.ltm.label if h.ltm else h.fy_labels[-1]


# --- headline --------------------------------------------------------------------------------------------------------
cols = st.columns(2)
for col, rep in zip(cols, reps):
    vd = rep.model.verdict
    imp = getattr(rep, "impact", None)
    with col:
        st.subheader(f"{rep.company.profile.name} ({rep.ticker})")
        st.caption(f"Report {rep.report_id} · {rep.created_at[:16].replace('T', ' ')} UTC")
        m1, m2 = st.columns(2)
        m1.metric("Price", money(vd.price))
        m2.metric("Fair value", money(vd.fair_value), delta=None if vd.gap is None else f"{vd.gap:+.1%} vs price")
        m1.metric("Verdict", vd.verdict or "n/a", help=f"Confidence: {vd.confidence}")
        m2.metric("MD rating", rep.md.rating if rep.md else "–",
                  help=f"Conviction: {rep.md.conviction}" if rep.md else "AI desks did not run")
        if imp is not None and not imp.error and imp.adjusted is not None:
            st.caption(f"News-adjusted fair value {money(imp.adjusted_fair_value)} (news as of "
                       f"{imp.as_of[:10]})")
        v = rep.model.valuation
        if v is None:
            fin = rep.model.financial
            st.caption(f"Toolkit: {fin.toolkit} (no DCF) · cost of equity {fin.cost_of_equity.value:.1%}")
        else:
            st.caption(f"Stage: {v.classification.stage_label} · Toolkit: {v.classification.toolkit} · WACC "
                       f"{v.wacc.wacc.value:.1%}")

# --- key metrics and multiples ---------------------------------------------------------------------------------------
st.markdown("### Key metrics")
table = []
for key, name, kind in METRICS:
    row = {"Metric": name}
    for rep in reps:
        p = latest_period(rep)
        val, used = rep.company.analysis.m(key, p), p
        if val is None:  # some ratios exist only for fiscal years (e.g. growth): fall back to the latest one
            used = rep.company.historicals_usd.fy_labels[-1]
            val = rep.company.analysis.m(key, used)
        row[f"{rep.ticker} ({p})"] = fmt(val, kind) + (f" ({used})" if used != p and val is not None else "")
    table.append(row)
st.dataframe(table, hide_index=True, width="stretch")

st.markdown("### Valuation multiples")
table = []
for key, name in MULTIPLES:
    row = {"Multiple": name}
    for rep in reps:
        cm = rep.model.company_metrics
        val = cm.multiples().get(key) if cm else None
        med = None
        if rep.model.comps and key in rep.model.comps.multiples:
            med = rep.model.comps.multiples[key].median
        row[rep.ticker] = fmt(val, "x")
        row[f"{rep.ticker} peer median"] = fmt(med, "x")
    table.append(row)
st.dataframe(table, hide_index=True, width="stretch")
st.caption("Multiples and peer medians are from each report's comparable-companies analysis (n/a where not "
           "meaningful, e.g. negative earnings).")

# --- football fields -------------------------------------------------------------------------------------------------
st.markdown("### Football fields")
cols = st.columns(2)
for col, rep in zip(cols, reps):
    with col:
        st.markdown(f"**{rep.ticker}**")
        football(rep)
