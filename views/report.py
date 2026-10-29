"""Run screen and report: live progress panel, report sections as they become ready, editable assumptions."""
from __future__ import annotations

import copy
import queue
import threading
import time

import streamlit as st

from desks.modelling import run_modelling
from desks.pipeline import DESKS, DONE, FAILED, RUNNING, SKIPPED, load, refresh_news, run_report
from exports.excel import export_bytes
from exports.pdf import build_pdf
from ui.format import CSS, STATE_COLOUR, STATE_ICON, money
from ui.report import render_report, verdict_card
from ui.state import get_services

svc = get_services()
st.markdown(CSS, unsafe_allow_html=True)


def progress_panel(status: dict, started: float, cost: float) -> str:
    finished = sum(1 for s, _ in status.values() if s in (DONE, FAILED, SKIPPED))
    running = sum(1 for s, _ in status.values() if s == RUNNING)
    pct = (finished + 0.5 * running) / len(DESKS)
    rows = []
    for d in DESKS:
        state, msg = status.get(d, ("waiting", "Waiting"))
        icon = STATE_ICON[state]
        rows.append(f"<div><span style='color:{STATE_COLOUR[state]};display:inline-block;width:1.2em'>"
                    f"{'<span class=\"vt-spin\">◌</span>' if state == RUNNING else icon}</span>"
                    f"<b style='display:inline-block;width:9.5em'>{d}</b> {msg}</div>")
    return (f"<style>@keyframes vtspin{{to{{transform:rotate(360deg)}}}}.vt-spin{{display:inline-block;"
            f"animation:vtspin 1s linear infinite}}</style>"
            f"<div class='vt-card vt-desk'><div style='background:#1f262e;border-radius:4px;height:8px;margin-bottom:8px'>"
            f"<div style='background:#4c8dff;width:{pct * 100:.0f}%;height:8px;border-radius:4px'></div></div>"
            f"<div class='vt-muted'>{pct:.0%} complete · {time.time() - started:,.0f}s elapsed · AI cost ${cost:.3f}</div>"
            + "".join(rows) + "</div>")


def start_run(ticker: str, overrides: dict | None = None) -> None:
    q: queue.Queue = queue.Queue()
    holder: dict = {}
    t = threading.Thread(target=lambda: holder.update(final=run_report(ticker, svc, q, overrides=overrides,
                                                                       holder=holder)), daemon=True)
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
        panel.markdown(progress_panel(run["status"], run["started"], cost), unsafe_allow_html=True)
        stage = "model" if rep is not None and rep.model is not None else ("data" if rep is not None and rep.company else None)
        if stage != shown_stage and stage is not None:
            shown_stage = stage
            with early.container():
                if stage == "model":
                    verdict_card(rep)
                    st.caption("AI desks are still writing the investment view…")
                else:
                    cd = rep.company
                    st.markdown(f"**{cd.profile.name}** · {cd.profile.sic_description} · reports in "
                                f"{cd.profile.reporting_currency}. Historicals loaded; valuation in progress…")
        if not run["thread"].is_alive() and run["q"].empty():
            break
        time.sleep(0.4)
    final = run["holder"].get("final")
    st.session_state.report = final
    st.session_state.pop("run", None)
    st.rerun()


def edit_form(rep) -> None:
    v = rep.model.valuation
    plan = v.plan
    with st.form("edit"):
        st.markdown("Edit any assumption; the whole valuation recalculates (AI commentary keeps the original view).")
        c1, c2, c3 = st.columns(3)
        g1 = c1.number_input("Revenue growth, year 1 (%)", value=round(plan.path("revenue_growth")[0] * 100, 2))
        g2 = c1.number_input("Revenue growth, year 2 (%)", value=round(plan.path("revenue_growth")[1] * 100, 2))
        tm = c2.number_input("Target operating margin (%)", value=round(plan.drivers["operating_margin"].chosen.value * 100, 2))
        s2c = c2.number_input("Sales-to-capital (x)", value=round(plan.drivers["sales_to_capital"].chosen.value, 2))
        tg = c3.number_input("Terminal growth (%)", value=round(plan.terminal_growth.value * 100, 2))
        troic = c3.number_input("Terminal ROIC (%)", value=round(plan.terminal_roic.value * 100, 2))
        c4, c5 = st.columns(2)
        beta_choice = c4.selectbox("Beta", ["industry", "regression"],
                                   index=0 if rep.overrides.get("beta_choice", "industry") == "industry" else 1)
        wacc = c4.number_input("WACC override (%, 0 = calculated)", value=0.0)
        w_dcf = c5.number_input("Weight: DCF (%)", value=50.0)
        w_comps = c5.number_input("Weight: comps (%)", value=30.0)
        w_hist = c5.number_input("Weight: historical multiples (%)", value=20.0)
        if st.form_submit_button("Recalculate"):
            ov = {**rep.overrides, "revenue_growth": [g1 / 100, g2 / 100], "target_margin": tm / 100,
                  "sales_to_capital": s2c, "terminal_growth": tg / 100, "terminal_roic": troic / 100,
                  "beta_choice": beta_choice,
                  "blend_weights": {"dcf": w_dcf / 100, "comps": w_comps / 100, "history": w_hist / 100}}
            if wacc > 0:
                ov["wacc"] = wacc / 100
            with st.spinner("Recalculating…"):
                edited = copy.copy(rep)
                edited.model = run_modelling(rep.company, svc, rep.valuation_date, ov, peers=rep.peers_pool,
                                             research=rep.research.data if rep.research else None)
                edited.overrides = ov
                edited.impact = None  # news effects were priced on the saved model, not on these assumptions
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
    st.info("Pick a stock on the Search page to run a report, or open a recent one.")
    st.stop()

top = st.columns([2, 1, 1, 1, 1])
top[0].caption(f"Saved report {rep.report_id}")
if getattr(rep, "save_error", None):
    st.warning(rep.save_error)
if top[1].button("Re-run (new version)"):
    start_run(rep.ticker, rep.overrides or None)
    st.rerun()
if rep.model is not None and "edited" not in st.session_state and \
        top[2].button("Refresh news", help="Re-runs the news desk only, then the impact analysis and the MD's news "
                                           "summary. The base valuation and rating stay as they are."):
    with st.spinner("Refreshing news: searching, verifying and analysing the impact (about a minute)…"):
        try:
            st.session_state.report = refresh_news(rep, svc)
        except Exception as exc:  # the saved report is still shown
            st.error(f"News refresh failed: {type(exc).__name__}: {exc}")
        else:
            st.rerun()
if rep.model is not None and rep.model.valuation.dcf is not None:
    try:
        top[3].download_button("Download Excel model", export_bytes(rep), file_name=f"{rep.report_id}.xlsx",
                               mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        top[4].download_button("Download PDF report", build_pdf(rep), file_name=f"{rep.report_id}.pdf",
                               mime="application/pdf")
    except Exception as exc:  # an export problem must not hide the report
        top[3].caption(f"Export unavailable: {exc}")
if "edited" in st.session_state:
    st.info("Showing your edited assumptions (not saved). Use Re-run to save a new dated version with AI commentary.")
    if st.button("Back to the saved version"):
        st.session_state.pop("edited")
        st.rerun()

render_report(rep)
if rep.model is not None and rep.model.valuation.dcf_inputs is not None:
    with st.expander("Edit assumptions (live recalculation)"):
        edit_form(rep)
with st.expander("Desk log"):
    for d, (state, msg) in rep.desk_status.items():
        st.markdown(f"{STATE_ICON.get(state, '·')} **{d}** — {msg}")
    if rep.model:
        for n in rep.model.notes:
            st.caption(n)
    st.caption(f"AI cost for this report: {money(rep.ai_cost, 3)}")
