"""Compare: two saved reports side by side (verdict, rating, key metrics, multiples, football fields).
Uses saved reports only, so it opens instantly at no API cost; every figure is the one in each report."""
from __future__ import annotations

import streamlit as st

from desks.pipeline import load
from ui.financial import _fmt
from ui.format import money, plain_table, when
from ui.report import football, value_strip
from ui.theme import ACCENT, RATING_COLOUR, VERDICT_COLOUR, esc, note
from ui.state import get_services

MULTIPLES = [("pe_trailing", "P/E (trailing)"), ("pe_forward", "P/E (forward)"), ("ev_sales", "EV/Sales"),
             ("ev_ebitda", "EV/EBITDA"), ("ev_fcf", "EV/FCF")]
METRICS = [("revenue_growth", "Revenue growth", "pct"), ("operating_margin", "Operating margin", "pct"),
           ("fcf_margin", "FCF margin", "pct"), ("roic", "ROIC", "pct"), ("net_debt_to_ebitda", "Net debt / EBITDA", "x"),
           ("interest_cover", "Interest cover", "x"), ("roe", "Return on equity", "pct")]
LOWER_IS_STRONGER = {"net_debt_to_ebitda"}
CORPORATE_ONLY = {"operating_margin", "fcf_margin", "roic", "net_debt_to_ebitda", "interest_cover"}

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
    st.markdown(note("Compare needs saved reports on at least two companies."), unsafe_allow_html=True)
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


def stronger(values: dict[str, float | None], lower_is_better: bool) -> str:
    """The ticker with the stronger figure, or "–" when either is missing or they tie."""
    vals = {t: x for t, x in values.items() if x is not None}
    if len(vals) < 2 or len(set(vals.values())) < 2:
        return "–"
    pick = min if lower_is_better else max
    return pick(vals, key=vals.get)


def latest_period(rep) -> str:
    h = rep.company.historicals_usd
    return h.ltm.label if h.ltm else h.fy_labels[-1]


# --- headline --------------------------------------------------------------------------------------------------------
def _kpi(label, value, sub="", colour=None, word=False):
    style = f" style='color:{colour}'" if colour else ""
    return (f"<div class='vt-kpi'><div class='l'>{esc(label)}</div><div class='v{' word' if word else ''}'{style}>"
            f"{esc(value)}</div><div class='s'>{esc(sub) or '&nbsp;'}</div></div>")


cols = st.columns(2)
for col, rep in zip(cols, reps):
    vd = rep.model.verdict
    imp = getattr(rep, "impact", None)
    v = rep.model.valuation
    if v is None:
        fin = rep.model.financial
        basis = f"{fin.toolkit.capitalize()} toolkit (no DCF) · cost of equity {fin.cost_of_equity.value:.1%}"
    else:
        basis = f"{v.classification.stage_label} · {v.classification.toolkit} toolkit · WACC {v.wacc.wacc.value:.1%}"
    adj = (f" · news-adjusted fair value {money(imp.adjusted_fair_value)} ({when(imp.as_of[:10])})"
           if imp is not None and not imp.error and imp.adjusted is not None else "")
    kpis = [_kpi("Price", money(vd.price)),
            _kpi("Fair value", money(vd.fair_value), "–" if vd.gap is None else f"{vd.gap:+.1%} vs price", ACCENT),
            _kpi("Verdict", vd.verdict or "–", f"Confidence: {vd.confidence or '–'}", VERDICT_COLOUR.get(vd.verdict), True),
            _kpi("MD rating", rep.md.rating if rep.md else "–",
                 f"Conviction: {rep.md.conviction}" if rep.md else "AI desks did not run",
                 RATING_COLOUR.get(rep.md.rating) if rep.md else None, True)]
    col.markdown(
        f"<div class='vt-head'><div class='vt-id'><span class='vt-ticker'>{esc(rep.ticker)}</span>"
        f"<span class='vt-name'>{esc(rep.company.profile.name)}</span></div>"
        f"<div class='vt-kpis two'>{''.join(kpis)}</div>{value_strip(rep.model)}"
        f"<div class='vt-stats'><span>{esc(basis)}{esc(adj)}</span><span>Report <span class='n'>"
        f"{esc(when(rep.created_at))}</span></span></div></div>", unsafe_allow_html=True)


# --- key metrics and multiples ---------------------------------------------------------------------------------------
st.markdown("### Key metrics")
table = []
for key, name, kind in METRICS:
    row, raw = {"Metric": name}, {}
    for rep in reps:
        p = latest_period(rep)
        if key in CORPORATE_ONLY and getattr(rep.model, "financial", None) is not None:
            row[f"{rep.ticker} ({p})"] = f"not meaningful ({rep.model.financial.toolkit})"
            continue
        val, used = rep.company.analysis.m(key, p), p
        if val is None:  # some ratios exist only for fiscal years (e.g. growth): fall back to the latest one
            used = rep.company.historicals_usd.fy_labels[-1]
            val = rep.company.analysis.m(key, used)
        row[f"{rep.ticker} ({p})"] = fmt(val, kind) + (f" ({used})" if used != p and val is not None else "")
        raw[rep.ticker] = val
    row["Stronger"] = stronger(raw, key in LOWER_IS_STRONGER)
    table.append(row)
st.markdown(plain_table([list(r.values()) for r in table], list(table[0].keys())), unsafe_allow_html=True)
st.caption("Stronger: the higher figure, except net debt / EBITDA where lower is stronger. Operating margin, FCF "
           "margin, ROIC, net debt / EBITDA and interest cover do not describe a bank, insurer or REIT; their sector "
           "metrics are below.")
for rep in reps:
    fin = getattr(rep.model, "financial", None)
    if fin is not None:
        st.markdown(f"##### {rep.ticker} sector metrics ({fin.period})")
        st.markdown(plain_table([[m.label, _fmt(m.value)] for m in fin.metrics], ["Metric", "Value"]),
                    unsafe_allow_html=True)

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
st.markdown(plain_table([list(r.values()) for r in table], list(table[0].keys())), unsafe_allow_html=True)
st.caption("Multiples and peer medians are from each report's comparable-companies analysis (n/a where not "
           "meaningful, e.g. negative earnings).")

# --- football fields -------------------------------------------------------------------------------------------------
st.markdown("### Football fields")
for rep in reps:  # stacked, not side by side: method names are long and need the width
    st.markdown(f"##### {rep.ticker}")
    football(rep)
