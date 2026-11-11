"""Position tab: size a holding in pounds (FX and Trading 212's fee included) and keep a thesis with exit conditions."""
from __future__ import annotations

from datetime import datetime, timezone

import streamlit as st

from engine.sizing import FX_FEE, size_position
from engine.thesis import LABEL, MAX_CONDITIONS, clean_conditions, overall
from ui.format import money
from ui.theme import AMBER, GREEN, RED, esc

STATUS_COLOUR = {"holding": GREEN, "at_risk": AMBER, "broken": RED, "no_evidence": "#8a8178"}


def gbp(x: float) -> str:
    return f"-£{abs(x):,.0f}" if x < 0 else f"£{x:,.0f}"


def usd_per_gbp(svc) -> tuple[float | None, str]:
    """FRED's latest daily GBP/USD (the report's one FX source) and its date, or (None, why)."""
    try:
        d, v, _ = svc.fred.latest("DEXUSUK")
        return v, d
    except Exception as exc:  # noqa: BLE001
        return None, f"FRED rate unavailable ({type(exc).__name__})"


def _portfolio_cell(o: dict) -> str:
    return "–" if o["pnl_pct_of_portfolio"] is None else f"{o['pnl_pct_of_portfolio']:+.1%}"


def position_panel(rep, svc) -> None:
    m = rep.model
    v = m.valuation if m else None
    price = m.verdict.price if m else None
    saved = svc.store.holding(rep.ticker) or {}
    st.markdown("#### Position sizing")
    rate, rate_note = usd_per_gbp(svc)
    c1, c2, c3 = st.columns(3)
    pos = c1.number_input("Position (£ put in)", min_value=0.0, value=float(saved.get("position_gbp") or 0.0),
                          step=100.0, key=f"pos_{rep.ticker}")
    entry = c2.number_input("Entry price (US$ per share)", min_value=0.0,
                            value=float(saved.get("entry_price") or (price or 0.0)), step=1.0,
                            key=f"entry_{rep.ticker}")
    port = c3.number_input("Portfolio (£, total)", min_value=0.0, value=float(saved.get("portfolio_gbp") or 0.0),
                           step=1000.0, key=f"port_{rep.ticker}")
    fx = st.number_input("US$ per £", min_value=0.0, value=float(rate or 0.0), step=0.001, format="%.4f",
                         key=f"fx_{rep.ticker}",
                         help="Defaults to FRED's latest daily GBP/USD. Overwrite it with your broker's rate if you "
                              "prefer. It is used both ways, so currency moves are not modelled.")
    source = rate_note if rate is None else f"FRED daily GBP/USD for {rate_note}"
    st.caption(f"Rate: {source}. FX fee {FX_FEE:.2%} each way (Trading 212). Loss is in pounds after both fees, with "
               "the exchange rate held.")
    if pos and entry and fx and v is not None:
        figs = v.dcf_figures or {}
        targets = {"Bear DCF": figs.get("bear"), "Base DCF": figs.get("base"), "Bull DCF": figs.get("bull")}
        try:
            r = size_position(pos, entry, fx, port or None, targets, current_price=price)
        except ValueError as exc:
            st.warning(str(exc))
        else:
            rows = ([("Now", r["now"])] if "now" in r else []) + list(r["outcomes"].items())
            head = ("<tr><th>If the price reaches</th><th>Share price</th><th>Value</th><th>Gain / loss</th>"
                    "<th>% of position</th><th>% of portfolio</th></tr>")
            body = "".join(
                f"<tr><td>{esc(n)}</td><td>{esc(money(o['price']))}</td><td>{esc(gbp(o['value_gbp']))}</td>"
                f"<td style='color:{GREEN if o['pnl_gbp'] >= 0 else RED}'>{esc(gbp(o['pnl_gbp']))}</td>"
                f"<td>{o['pnl_pct']:+.1%}</td><td>{_portfolio_cell(o)}</td></tr>" for n, o in rows)
            st.markdown(f"<div class='vt-scroll'><table class='vt-table'>{head}{body}</table></div>",
                        unsafe_allow_html=True)
            share = r["share_of_portfolio"]
            where = "not compared with a portfolio (none entered)" if share is None else f"{share:.1%} of the portfolio"
            st.caption(f"{r['units']:,.3f} shares. Position is {where}. FX fee on the way in: {gbp(r['fee_in_gbp'])}; "
                       f"a round trip costs {r['round_trip_fee_drag']:.2%}.")
            if r["missing"]:
                st.caption("Not in this report's DCF: " + ", ".join(r["missing"]))
    elif v is None:
        st.caption("This report has no DCF, so there are no bear and base prices to test against.")
    else:
        st.caption("Enter a position, an entry price and a rate to see the outcomes.")

    st.markdown("#### Thesis and exit conditions")
    thesis = st.text_area("Thesis", value=saved.get("thesis") or "", key=f"thesis_{rep.ticker}", height=90)
    st.caption(f"Up to {MAX_CONDITIONS} things that would prove you wrong, each a fact a filing or news item can show "
               "(for example: \"NVDA data centre revenue misses guidance\"). The check sees only these lines, never "
               "your thesis or position.")
    existing = list(saved.get("conditions") or [])
    inputs = [st.text_input(f"Condition {i + 1}", value=existing[i] if i < len(existing) else "",
                            key=f"cond_{rep.ticker}_{i}") for i in range(MAX_CONDITIONS)]
    b1, b2 = st.columns(2)
    holding = dict(position_gbp=pos or None, entry_price=entry or None, portfolio_gbp=port or None, thesis=thesis)
    if b1.button("Save position and thesis", key=f"save_{rep.ticker}"):
        try:
            svc.store.save_holding(rep.ticker, conditions=clean_conditions(inputs), **holding)
            st.success("Saved.")
        except ValueError as exc:
            st.error(str(exc))
    if b2.button("Check conditions against this report", key=f"check_{rep.ticker}"):
        try:
            conds = clean_conditions(inputs)
        except ValueError as exc:
            st.error(str(exc))
            conds = []
        if conds:
            from desks.thesis import run_thesis_check
            with st.spinner("Reading the latest filings and news…"):
                try:
                    results, _ = run_thesis_check(svc.ai, f"thesis-{rep.report_id}", rep, conds)
                except Exception as exc:  # noqa: BLE001
                    st.error(f"The check could not run: {type(exc).__name__}: {exc}")
                else:
                    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
                    svc.store.save_holding(rep.ticker, conditions=conds, **holding)
                    svc.store.save_checks(rep.ticker, now, rep.report_id, results)
    last = svc.store.last_checks(rep.ticker)
    if last:
        when = last["checked_at"][:16].replace("T", " ")
        st.markdown(f"**Last check {esc(when)} UTC** (report {esc(last['report_id'])})")
        conds_now = (svc.store.holding(rep.ticker) or {}).get("conditions") or []
        for r in last["results"]:
            name = conds_now[r["index"]] if r["index"] < len(conds_now) else f"Condition {r['index'] + 1}"
            ev = f" — “{r['evidence']}” ({r.get('source', '')}, {r.get('date', '')})" if r.get("evidence") else ""
            st.markdown(f"<span style='color:{STATUS_COLOUR[r['status']]};font-weight:600'>{esc(LABEL[r['status']])}"
                        f"</span> · {esc(name)}{esc(ev)}<br><span style='color:var(--vt-muted)'>"
                        f"{esc(r.get('reason', ''))}</span>", unsafe_allow_html=True)
        top = overall(last["results"])
        if top in ("broken", "at_risk"):
            st.warning(f"Overall: {LABEL[top]}. Review the thesis before adding to this position.")
