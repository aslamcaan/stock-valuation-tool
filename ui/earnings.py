"""Earnings tab: a preview that opens within 14 days of the results (data from desks.earnings_preview)."""
from __future__ import annotations

import streamlit as st

from desks.earnings_preview import build_preview
from ui.format import money, when
from ui.theme import GREEN, RED, esc


def earnings_panel(rep, svc) -> None:
    p = build_preview(rep, svc)
    ne = p["next"]
    if not ne:
        st.caption(p["notes"][0])
        return
    head = f"**Next results: {when(ne['date'])}**" + (f", {p['session']}" if p.get("session") else
                                                      " (the time of day is not known)")
    st.markdown(head + f" · in {p['days']} days · Source: earnings calendar (FMP, Finnhub).")
    if p.get("days") is None or p["days"] < 0 or p["days"] > 14 or "consensus" not in p:
        st.caption(p["notes"][-1])
        return
    c = p["consensus"]
    st.markdown("#### Consensus")
    st.markdown("EPS estimate " + (f"**{money(c['eps'])}**" if c.get("eps") is not None else "not available")
                + " · revenue estimate " + (f"**{money(c['revenue'] / 1e6, 0)}m**" if c.get("revenue") else "not available"))
    st.markdown("#### Guidance on file")
    if p["guidance"]:
        for g in p["guidance"][:4]:
            st.markdown(f"- **{esc(g.get('metric', ''))}** ({esc(g.get('period', ''))}): {esc(g.get('guidance_text', ''))}")
        st.caption("From the latest annual report. The newest quarterly guidance is in the earnings release"
                   + (f": [{p['release']['headline']}]({p['release']['url']}) ({p['release']['date']})." if p.get("release") else "."))
    else:
        st.caption("No guidance was extracted from the annual report.")
    st.markdown("#### Numbers that matter")
    if p["watch"]:
        for w in p["watch"]:
            st.markdown(f"- **{esc(w['label'])}**: {esc(w['why'])}" + (f"  \n  “{esc(w['quote'])}”" if w.get("quote") else ""))
    else:
        st.caption("No key figures could be chosen from the filing extracts.")
    st.markdown("#### Last eight reactions")
    if p["moves"]:
        s = p["summary"]
        rows = "".join(
            f"<tr><td>{esc(m['date'])}</td><td style='color:{GREEN if m['move'] > 0 else RED}'>{m['move']:+.1%}</td>"
            f"<td>{esc(m['basis'])}</td><td>{'–' if m['eps_actual'] is None else money(m['eps_actual'])}</td>"
            f"<td>{'–' if m['eps_estimate'] is None else money(m['eps_estimate'])}</td></tr>" for m in p["moves"])
        st.markdown("<div class='vt-scroll'><table class='vt-table'><tr><th>Results</th><th>Move</th><th>Window</th>"
                    f"<th>EPS actual</th><th>EPS estimate</th></tr>{rows}</table></div>", unsafe_allow_html=True)
        st.caption(f"Typical move (average of the last {s['n']}): ±{s['mean_abs']:.1%}; up {s['up']} of {s['n']} times; "
                   f"largest {s['largest']['move']:+.1%} on {s['largest']['date']}.")
    else:
        st.caption("No past reactions could be computed.")
    for n in p["notes"]:
        st.caption(n)
