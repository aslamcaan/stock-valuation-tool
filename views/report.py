"""Run screen and report: live progress panel, report sections as they become ready, editable assumptions."""
from __future__ import annotations

import copy
import logging
import queue
import threading
import time

import streamlit as st

from desks.modelling import run_modelling
from desks.pipeline import DESKS, load, refresh_news, run_report
from engine.valuation import ValuationError
from exports.excel import export_bytes
from exports.pdf import build_pdf
from ui.format import CSS, money
from ui.report import render_report, verdict_card, what_changed, what_if
from ui.run_panel import desk_nodes, panel as run_panel
from ui.state import get_services

svc = get_services()
st.markdown(CSS, unsafe_allow_html=True)


def start_run(ticker: str, overrides: dict | None = None) -> None:
    q: queue.Queue = queue.Queue()
    holder: dict = {}

    def work():
        try:
            holder["final"] = run_report(ticker, svc, q, overrides=overrides, holder=holder)
        except Exception as exc:  # shown on the page instead of silently returning to "Pick a stock"
            logging.getLogger(__name__).exception("Report run failed for %s", ticker)  # traceback in the server log
            holder["error"] = f"{type(exc).__name__}: {exc}"
    t = threading.Thread(target=work, daemon=True)
    t.start()
    st.session_state.run = {"ticker": ticker, "q": q, "holder": holder, "thread": t, "started": time.time(),
                            "status": {d: ("waiting", "Waiting") for d in DESKS}}
    st.session_state.pop("edited", None)


def watch_run() -> None:
    run = st.session_state.run
    panel, early = st.empty(), st.empty()
    shown_stage = None
    while True:
        while not run["q"].empty():
            e = run["q"].get()
            run["status"][e.desk] = (e.state, e.message)
        rep = run["holder"].get("report")
        cost = svc.ai.report_cost(rep.report_id) if rep else 0.0
        panel.markdown(run_panel(run, rep, cost), unsafe_allow_html=True)
        stage = "model" if rep is not None and rep.model is not None else ("data" if rep is not None and rep.company else None)
        if stage != shown_stage and stage is not None:
            shown_stage = stage
            with early.container():
                if stage == "model":
                    st.markdown("#### First look: the model's numbers (the AI desks are still writing)")
                    verdict_card(rep)
        if not run["thread"].is_alive() and run["q"].empty():
            break
        time.sleep(0.4)
    final = run["holder"].get("final")
    if final is None and run["holder"].get("error"):
        st.session_state.run_error = run["holder"]["error"]
    st.session_state.report = final
    st.session_state.pop("run", None)
    st.rerun()


def edit_form(rep) -> None:
    v = rep.model.valuation
    plan = v.plan
    with st.form("edit"):
        st.markdown("Edit any assumption; the whole valuation recalculates (AI commentary keeps the original view).")
        c1, c2, c3 = st.columns(3)
        gp = plan.path("revenue_growth")  # starts with any ended-but-unreported year, which is forecast too
        g1 = c1.number_input(f"Revenue growth, {plan.labels[0]} (%)", value=round(gp[0] * 100, 2))
        g2 = c1.number_input(f"Revenue growth, {plan.labels[1]} (%)", value=round(gp[1] * 100, 2))
        tm = c2.number_input("Target operating margin (%)", value=round(plan.drivers["operating_margin"].chosen.value * 100, 2))
        s2c = c2.number_input("Sales-to-capital (x)", value=round(plan.drivers["sales_to_capital"].chosen.value, 2))
        tg = c3.number_input("Terminal growth (%)", value=round(plan.terminal_growth.value * 100, 2))
        troic = c3.number_input("Terminal ROIC (%)", value=round(plan.terminal_roic.value * 100, 2))
        c4, c5 = st.columns(2)
        beta_choice = c4.selectbox("Beta", ["industry", "regression"],
                                   index=0 if rep.overrides.get("beta_choice", "industry") == "industry" else 1)
        wacc = c4.number_input("WACC override (%, 0 = calculated)",
                               value=round(rep.overrides["wacc"] * 100, 2) if rep.overrides.get("wacc") else 0.0)
        bw = rep.overrides.get("blend_weights") or {"dcf": 0.5, "comps": 0.3, "history": 0.2}
        w_dcf = c5.number_input("Weight: DCF (%)", value=round(bw.get("dcf", 0) * 100, 1))
        w_comps = c5.number_input("Weight: comps (%)", value=round(bw.get("comps", 0) * 100, 1))
        w_hist = c5.number_input("Weight: historical multiples (%)", value=round(bw.get("history", 0) * 100, 1))
        if st.form_submit_button("Recalculate"):
            ov = {**rep.overrides, "revenue_growth": [g1 / 100, g2 / 100], "target_margin": tm / 100,
                  "sales_to_capital": s2c, "terminal_growth": tg / 100, "terminal_roic": troic / 100,
                  "beta_choice": beta_choice,
                  "blend_weights": {"dcf": w_dcf / 100, "comps": w_comps / 100, "history": w_hist / 100}}
            if wacc > 0:
                ov["wacc"] = wacc / 100
            else:
                ov.pop("wacc", None)  # 0 means "calculated": clear an earlier override
            try:
                with st.spinner("Recalculating…"):
                    edited = copy.copy(rep)
                    edited.model = run_modelling(rep.company, svc, rep.valuation_date, ov, peers=rep.peers_pool,
                                                 research=rep.research.data if rep.research else None)
                    edited.overrides = ov
                    edited.impact = None  # news effects were priced on the saved model, not on these assumptions
            except ValuationError as exc:
                st.error(f"These assumptions cannot be valued, so the report is unchanged. {exc}")
            else:
                st.session_state.edited = edited
                st.rerun()


def edit_form_financial(rep) -> None:
    """Banks, insurers, REITs: cost of equity, long-run growth, normalised return, cap rate and blend weights."""
    from engine.financials import method_label
    fv = rep.model.financial
    with st.form("edit_fin"):
        st.markdown("Edit any assumption; the valuation recalculates (AI commentary keeps the original view).")
        c1, c2, c3 = st.columns(3)
        coe = c1.number_input("Cost of equity (%)", value=round(fv.cost_of_equity.value * 100, 2))
        g = c1.number_input("Long-run growth (%)", value=round(fv.growth.value * 100, 2))
        normal = c2.number_input("Normalised return on equity (%)", value=round(fv.normalised_return.value * 100, 2))             if fv.normalised_return is not None else None
        cap0 = fv.detail["nav"]["cap_rate"] * 100 if "nav" in fv.detail else None
        cap = c2.number_input("Cap rate (%)" + ("" if cap0 is not None else " (no peer cap rate: enter one to add NAV)"),
                              value=round(cap0, 2) if cap0 is not None else 0.0) if fv.toolkit == "reit" else None
        weights = {k: c3.number_input(f"Weight: {method_label(k, fv.toolkit)} (%)", value=round(w * 100, 1))
                   for k, w in fv.weights.items()}
        if st.form_submit_button("Recalculate"):
            # only what the user changed becomes an override, so derived inputs (growth from return x retention)
            # keep following the others
            ov = dict(rep.overrides)

            def changed(new, old):
                return new is not None and old is not None and abs(new - round(old * 100, 2)) > 1e-9
            if changed(coe, fv.cost_of_equity.value):
                ov["cost_of_equity"] = coe / 100
            if changed(g, fv.growth.value):
                ov["long_run_growth"] = g / 100
            if fv.normalised_return is not None and changed(normal, fv.normalised_return.value):
                ov["normalised_return"] = normal / 100
            if cap is not None and (changed(cap, cap0 / 100) if cap0 is not None else cap > 0):
                ov["cap_rate"] = cap / 100
            if any(abs(w - round(fv.weights[k] * 100, 1)) > 1e-9 for k, w in weights.items()):
                ov["blend_weights"] = {k: w / 100 for k, w in weights.items()}
            try:
                with st.spinner("Recalculating…"):
                    edited = copy.copy(rep)
                    edited.model = run_modelling(rep.company, svc, rep.valuation_date, ov, peers=rep.peers_pool)
                    edited.overrides = ov
                    edited.impact = None
            except ValuationError as exc:
                st.error(f"These assumptions cannot be valued, so the report is unchanged. {exc}")
            else:
                st.session_state.edited = edited
                st.rerun()


# --- page ------------------------------------------------------------------------------------------------------------
if "run" in st.session_state:
    st.title(f"Analysing {st.session_state.run['ticker']}")
    watch_run()
elif st.session_state.get("start_ticker"):
    t = st.session_state.pop("start_ticker")
    start_run(t)
    st.rerun()
elif st.session_state.get("open_id"):
    st.session_state.report = load(st.session_state.pop("open_id"), svc.store)
    st.session_state.pop("edited", None)
    st.rerun()

rep = st.session_state.get("edited") or st.session_state.get("report")
if rep is None:
    st.title("Report")
    if st.session_state.get("run_error"):
        st.error(f"The report could not be completed: {st.session_state.pop('run_error')}")
    st.info("Pick a stock on the Search page to run a report, or open a recent one.")
    st.stop()

if getattr(rep, "save_error", None):
    st.warning(rep.save_error)
exportable = rep.model is not None and (getattr(rep.model, "financial", None) is not None or
                                        (rep.model.valuation is not None and rep.model.valuation.dcf is not None))
bar = st.columns([3.2, 1, 1, 1, 1], vertical_alignment="center")
bar[0].caption(f"Saved report {rep.report_id}")
if bar[1].button("Re-run", icon=":material/refresh:", width="stretch",
                 help="Runs every desk again and saves a new dated version (the saved one is kept)."):
    start_run(rep.ticker, rep.overrides or None)
    st.rerun()
if rep.model is not None and "edited" not in st.session_state and \
        bar[2].button("News", icon=":material/newspaper:", width="stretch",
                      help="Refresh news: re-runs the news desk only, then the impact analysis and the MD's news "
                           "summary. The base valuation and rating stay as they are."):
    with st.spinner("Refreshing news: searching, verifying and analysing the impact (about a minute)…"):
        try:
            st.session_state.report = refresh_news(rep, svc)
        except Exception as exc:  # the saved report is still shown
            st.error(f"News refresh failed: {type(exc).__name__}: {exc}")
        else:
            st.rerun()
if exportable:
    try:
        bar[3].download_button("Excel", export_bytes(rep), file_name=f"{rep.report_id}.xlsx", icon=":material/table_view:",
                               mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                               width="stretch", help="The full model with live formulas.")
        bar[4].download_button("PDF", build_pdf(rep), file_name=f"{rep.report_id}.pdf", icon=":material/picture_as_pdf:",
                               mime="application/pdf", width="stretch", help="The report as a research note.")
    except Exception as exc:  # an export problem must not hide the report
        bar[3].caption(f"Export unavailable: {exc}")
if "edited" in st.session_state:
    c1, c2 = st.columns([4, 1], vertical_alignment="center")
    c1.info("Showing your edited assumptions (not saved). Use Re-run to save a new dated version with AI commentary.")
    if c2.button("Back to the saved version", width="stretch"):
        st.session_state.pop("edited")
        st.rerun()


def _edit_tab() -> None:
    st.markdown("#### Edit assumptions")
    if rep.model is not None and getattr(rep.model, "financial", None) is not None:
        edit_form_financial(rep)
    elif rep.model is not None and rep.model.valuation.dcf_inputs is not None:
        edit_form(rep)
    else:
        st.caption("This report has no model to recalculate.")


def _log_tab() -> None:
    st.markdown("#### Desk log")
    st.markdown(desk_nodes(rep.desk_status), unsafe_allow_html=True)
    if rep.model:
        for n in rep.model.notes:
            st.caption(n)
    st.caption(f"AI cost for this report: {money(rep.ai_cost, 3)}")


@st.cache_data(show_spinner=False, max_entries=300)
def version_facts(report_id: str) -> dict:
    """The figures of one saved version that explain a change between runs (empty if it cannot be read)."""
    try:
        r = load(report_id, get_services().store)
    except Exception:  # a deleted or unreadable version still shows its logged call
        return {}
    m = r.model
    if m is None:
        return {}
    out = {"components": dict(m.verdict.components or {}), "price": m.verdict.price,
           "rating": r.md.rating if r.md else None,
           "reason": (r.md.view.get("reasoning_lines") or [""])[0] if r.md else ""}
    v = m.valuation
    if v is not None and v.plan is not None:
        k = len(v.plan.skipped)
        out.update(wacc=v.wacc.wacc.value, growth=v.plan.path("revenue_growth")[k],
                   margin=v.plan.drivers["operating_margin"].chosen.value, stage=v.classification.stage_label)
    return out


def _history_tab() -> None:
    import plotly.graph_objects as go
    from ui.theme import ACCENT, RATING_COLOUR, TEXT, VERDICT_COLOUR, esc, plotly_layout
    st.markdown("#### History")
    calls = sorted((c for c in svc.store.calls() if c["ticker"] == rep.ticker),
                   key=lambda c: (c["call_date"], c.get("call_time") or ""))
    if len(calls) < 2:
        st.caption(f"This is the only completed report for {rep.ticker}. Re-run it later to see how the call moves.")
        return
    xs = [f"{c['call_date']} {c.get('call_time') or ''}".strip() for c in calls]
    fig = go.Figure()
    fig.add_scatter(x=xs, y=[c["price"] for c in calls], name="Price", mode="lines+markers",
                    line=dict(color=TEXT, width=1.5, dash="dot"), marker=dict(size=6),
                    hovertemplate="Price %{y:$,.2f}<extra></extra>")
    fig.add_scatter(x=xs, y=[c["fair_value"] for c in calls], name="Fair value", mode="lines+markers+text",
                    line=dict(color=ACCENT, width=2.5), marker=dict(size=9),
                    text=[c.get("rating") or c.get("verdict") or "" for c in calls], textposition="top center",
                    textfont=dict(size=11, color=ACCENT), hovertemplate="Fair value %{y:$,.2f}<extra></extra>")
    fig.update_layout(**plotly_layout(height=320, showlegend=True, xaxis=dict(type="category"),
                                      legend=dict(orientation="h", y=1.12, x=0)))
    st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})
    st.caption("Orange: the tool's fair value at each run, labelled with the MD's rating (or the verdict when the AI "
               "desks did not run). Dotted: the share price at the time.")
    facts = [version_facts(c["report_id"]) for c in calls]
    items = []
    for i in range(len(calls) - 1, -1, -1):  # newest first
        c, f = calls[i], facts[i]
        label = c.get("rating") or c.get("verdict") or "–"
        colour = RATING_COLOUR.get(c.get("rating")) or VERDICT_COLOUR.get(c.get("verdict"), ACCENT)
        gap = c["fair_value"] / c["price"] - 1 if c.get("price") else None
        head = (f"<b style='color:{colour}'>{esc(label)}</b> · fair value {esc(money(c['fair_value']))} vs price "
                f"{esc(money(c['price']))}" + (f" ({gap:+.0%})" if gap is not None else ""))
        if i == 0:
            body = "First completed report."
        else:
            prev = calls[i - 1]
            move = c["fair_value"] / prev["fair_value"] - 1 if prev.get("fair_value") else None
            changes = what_changed(facts[i - 1], f) if f and facts[i - 1] else []
            body = ((f"Fair value {move:+.1%}" if move is not None else "")
                    + (": " + "; ".join(changes) if changes else
                       (" (the inputs that drive it barely moved)" if f and facts[i - 1] else "")) + ".")
            if (prev.get("rating") or None) != (c.get("rating") or None) and c.get("rating"):
                body += f" Rating {prev.get('rating') or 'not rated'} → {c['rating']}."
        if f.get("reason"):
            body += f" MD: {f['reason']}"
        items.append(f"<div class='ev'>{head}<span class='d'>{esc(xs[i])}</span><p>{esc(body)}</p></div>")
    st.markdown("<div class='vt-timeline'>" + "".join(items) + "</div>", unsafe_allow_html=True)


def _what_if_tab() -> None:
    st.markdown("#### What if")
    if rep.model is None:
        st.caption("This report has no model to reprice.")
        return
    what_if(rep)


render_report(rep, extra_tabs=[("What if", _what_if_tab), ("History", _history_tab),
                               ("Edit assumptions", _edit_tab), ("Desk log", _log_tab)])
