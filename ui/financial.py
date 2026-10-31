"""Report sections for the financial-sector toolkits (banks, insurers, REITs). PROMPT.md section 8: same report
structure, with the analysis and valuation sections changed and a plain statement of why a DCF isn't used."""
from __future__ import annotations

import streamlit as st

from engine.classify import BANK, INSURER, REIT
from engine.financials import method_label
from engine.values import MULTIPLE, PER_SHARE, RATIO
from ui.format import money, mult, pct, plain_table, trace_text, traced_table
from ui.theme import note

FS_LINES = {
    BANK: ["net_interest_income", "noninterest_income", "noninterest_expense", "provision_credit_losses",
           "net_income_attributable", "net_income_common", "dps_declared", "total_assets", "loans_gross",
           "loan_allowance", "nonaccrual_loans", "net_charge_offs", "deposits", "goodwill", "intangibles",
           "preferred_equity", "parent_equity", "shares_outstanding"],
    INSURER: ["premiums_written", "premiums_earned", "losses_incurred", "acquisition_cost_amortisation",
              "net_investment_income", "prior_year_development", "net_income_attributable", "net_income_common",
              "dps_declared", "total_assets", "claims_reserve", "goodwill", "intangibles", "parent_equity",
              "shares_outstanding"],
    REIT: ["revenue", "operating_income", "d_and_a", "real_estate_impairment", "real_estate_gains",
           "net_income_common", "dps_declared", "real_estate_gross", "real_estate_net", "total_debt",
           "cash_and_investments", "parent_equity", "shares_diluted_weighted", "shares_outstanding"],
}


def _fmt(v) -> str:
    if v is None or v.value is None:
        return "–"
    if v.unit == RATIO:
        return pct(v.value, 2)
    if v.unit == PER_SHARE:
        return money(v.value)
    if v.unit == MULTIPLE:
        return mult(v.value)
    return f"{v.value:,.0f}"


def html(s: str) -> None:
    st.markdown(s, unsafe_allow_html=True)


def sector_metrics(rep) -> None:
    fv = rep.model.financial
    st.caption(f"Fiscal year {fv.period}. 'Computed' is calculated by the tool from XBRL; 'Reported' is the company's "
               "own figure, read from the 10-K text (hover for the quote). Where the two differ, definitions differ "
               "(e.g. average interest-earning assets vs total assets).")
    groups: dict[str, list] = {}
    for m in fv.metrics:
        groups.setdefault(m.group, []).append(m)
    for g, ms in groups.items():
        st.markdown(f"**{g}**")
        html(traced_table([(m.label, [m.value if m.value.value is not None else None, m.reported]) for m in ms],
                          ["Computed", "Reported (10-K)"], formatter=_fmt))
        for m in ms:
            if m.value.value is None and m.reported is None and m.value.note:
                st.caption(f"{m.label}: {m.value.note}")


def toolkit_section(rep) -> None:
    fv = rep.model.financial
    c = rep.company.profile
    st.markdown(f"**Toolkit: {fv.toolkit}.** SIC {c.sic} ({c.sic_description}).")
    st.markdown(fv.why_no_dcf)


def methods_section(rep) -> None:
    fv, tk = rep.model.financial, rep.model.financial.toolkit
    vd = rep.model.verdict
    rows = [[method_label(k, tk), money(v.value), pct(vd.weights_used.get(k), 0) if k in vd.weights_used else "–"]
            for k, v in fv.methods.items()]
    html(plain_table(rows, ["Method", "Value per share", "Weight"]))
    missing = [method_label(k, tk) for k in fv.weights if k not in fv.methods]
    if missing:
        st.caption("Not available: " + "; ".join(missing) + ". Remaining weights rescaled.")
    d = fv.detail
    if "justified" in d:
        j = d["justified"]
        base = "tangible book" if tk == BANK else "book"
        st.markdown(f"**{method_label('justified', tk)}.** ({pct(j['return'])} - {pct(j['g'])}) / "
                    f"({pct(j['coe'])} - {pct(j['g'])}) = **{j['multiple']:.2f}x** {base} of {money(j['base'])} "
                    f"per share.")
    if "residual_income" in d:
        ri = d["residual_income"]
        st.markdown(f"**{method_label('residual_income', tk)}.** Return moves from {pct(ri['latest_return'])} to the "
                    f"normalised level over 3 years, then fades to {pct(ri['long_run_return'])} by year 10; book grows "
                    f"with retained earnings ({pct(ri['retention'], 0)} retained).")
        html(plain_table([[str(r["year"]), money(r["opening_book"]), pct(r["return"]), money(r["residual_income"]),
                           f"{r['discount_factor']:.3f}", money(r["pv"])] for r in ri["rows"]],
                         ["Year", "Opening book / share", "Return", "Residual income", "Discount factor", "PV"]))
        st.caption(f"Book today {money(ri['rows'][0]['opening_book'])} + PV explicit {money(ri['pv_explicit'])} + "
                   f"PV terminal {money(ri['pv_terminal'])} = {money(ri['value'])} per share.")
    if "ddm" in d:
        dd = d["ddm"]
        st.markdown(f"**{method_label('ddm', tk)}.** Last dividend {money(dd['dps0'])}; stage-1 growth "
                    f"{pct(dd['stage1_growth'])} ({dd['stage1_note']}), then long-run growth {pct(fv.growth.value)}.")
        html(plain_table([[str(r["year"]), money(r["dividend"]), f"{r['discount_factor']:.3f}", money(r["pv"])]
                          for r in dd["rows"]], ["Year", "Dividend", "Discount factor", "PV"]))
        st.caption(f"PV dividends {money(dd['pv_explicit'])} + PV terminal {money(dd['pv_terminal'])} = "
                   f"{money(dd['value'])} per share.")
    if "nav" in d:
        n = d["nav"]
        st.markdown(f"**{method_label('nav', tk)}.** NOI proxy {n['noi']:,.0f} / cap rate {pct(n['cap_rate'], 2)} = "
                    f"gross asset value {n['gross_asset_value']:,.0f}, less net debt {n['net_debt']:,.0f} (US$m).")
    for k in ("cap_rate", "comps_pb", "comps_pe", "comps_pffo"):
        if k in d and d[k].get("peers"):
            name = {"cap_rate": "Peer implied cap rates (NOI / EV)"}.get(k) or method_label(k, tk)
            st.markdown(f"**{name}**" + ("" if d[k].get("median") is None else
                        f": median {pct(d[k]['median'], 2) if k == 'cap_rate' else mult(d[k]['median'])}"))
            html(plain_table([[p["ticker"], p["name"], pct(p["multiple"], 2) if k == "cap_rate" else
                               mult(p["multiple"]), p["period"]] for p in d[k]["peers"]],
                             ["Ticker", "Name", "Multiple", "Period"]))
            if d[k].get("median") is None:
                st.caption("Fewer than three usable peers: this method is not used.")


def cost_of_equity_section(rep) -> None:
    fv, i = rep.model.financial, rep.model.inputs
    beta = next((a for a in rep.model.assumptions if a["name"] == "Beta (levered)"), None)
    rows = [("Risk-free rate", [i.risk_free]), ("Equity risk premium", [i.erp]), ("Country risk premium", [i.crp]),
            ("Cost of equity", [fv.cost_of_equity]), ("Long-run growth", [fv.growth])]
    if fv.normalised_return is not None:
        rows.append(("Normalised return", [fv.normalised_return]))
    html(traced_table(rows, ["Value"], formatter=lambda v: pct(v.value, 2)))
    if beta:
        st.caption(f"Beta (levered) {beta['value']:.2f}: {beta['source']}. {beta.get('note') or ''}")
    st.caption(trace_text(fv.cost_of_equity))


def sector_benchmarks(rep) -> None:
    fv = rep.model.financial
    peers = {p["ticker"] for k in ("comps_pb", "comps_pe", "comps_pffo", "cap_rate")
             for p in fv.detail.get(k, {}).get("peers", [])}
    if not peers:
        st.markdown(note("No usable peers, so peer comparison is not available."), unsafe_allow_html=True)
        return
    st.markdown("Peer multiples are in section 7 (valuation methods). Peers: " + ", ".join(sorted(peers)))


SECTIONS_FIN = [
    ("4. Sector metrics", sector_metrics), ("5. Peer comparison", sector_benchmarks),
    ("6. Toolkit and why no DCF", toolkit_section), ("7. Valuation methods", methods_section),
    ("9. Cost of equity", cost_of_equity_section),
]
