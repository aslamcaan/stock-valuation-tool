"""Run screen and report: live progress panel, report sections as they become ready, editable assumptions."""
from __future__ import annotations

import copy
import queue
import threading
import time

import streamlit as st

from desks.modelling import run_modelling
from desks.pipeline import DESKS, DONE, FAILED, RUNNING, SKIPPED, load, refresh_news, run_report
from engine.valuation import ValuationError
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

    def work():
        try:
            holder["final"] = run_report(ticker, svc, q, overrides=overrides, holder=holder)
        except Exception as exc:  # shown on the page instead of silently returning to "Pick a stock"
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
exportable = rep.model is not None and (getattr(rep.model, "financial", None) is not None or
                                        (rep.model.valuation is not None and rep.model.valuation.dcf is not None))
if exportable:
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
if rep.model is not None and getattr(rep.model, "financial", None) is not None:
    with st.expander("Edit assumptions (live recalculation)"):
        edit_form_financial(rep)
elif rep.model is not None and rep.model.valuation.dcf_inputs is not None:
    with st.expander("Edit assumptions (live recalculation)"):
        edit_form(rep)
with st.expander("Desk log"):
    for d, (state, msg) in rep.desk_status.items():
        st.markdown(f"{STATE_ICON.get(state, '·')} **{d}** — {msg}")
    if rep.model:
        for n in rep.model.notes:
            st.caption(n)
    st.caption(f"AI cost for this report: {money(rep.ai_cost, 3)}")
