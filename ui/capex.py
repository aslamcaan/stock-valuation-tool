"""AI capex tracker panel: the latest stated capex outlook of the five hyperscalers, verbatim, dated and linked. Reusable:
`capex_panel(svc)` draws it anywhere; a report shows it as a tab when data centre or AI revenue is above 30% of sales."""
from __future__ import annotations

import streamlit as st

from desks.capex import capex_tracker
from engine.capex import AI_SHARE_THRESHOLD, qualifies
from ui.format import when
from ui.theme import AMBER, esc


@st.cache_data(show_spinner="Reading the latest filings of MSFT, AMZN, GOOGL, META and ORCL…", ttl=6 * 3600)
def _rows(_svc, day: str) -> list[dict]:
    return capex_tracker(_svc)


def capex_panel(svc, context: str = "") -> None:
    from datetime import date
    if context:
        st.caption(context)
    for r in _rows(svc, date.today().isoformat()):
        st.markdown(f"**{esc(r['ticker'])}**")
        for s in r["statements"]:
            stale = f" <span style='color:{AMBER}'>older than 120 days</span>" if s["stale"] else ""
            st.markdown(f"“{esc(s['quote'])}”  \n<span style='color:var(--vt-muted)'>{esc(s['form'])} filed "
                        f"{esc(when(s['filed']))} · <a href='{esc(s['url'])}' target='_blank'>source</a>{stale}</span>",
                        unsafe_allow_html=True)
        for n in r["notes"]:
            st.caption(n)
    st.caption("Sentences are copied from the companies' own filings (earnings release, else latest 10-Q or 10-K) by "
               "rule; nothing is paraphrased. Where a company gives its outlook only on the earnings call, none is "
               "shown, because call transcripts are not a free source.")


def attaches(rep) -> tuple[bool, str]:
    """(show the panel on this report, why or why not)."""
    cd = getattr(rep, "company", None)
    research = getattr(getattr(rep, "research", None), "data", None)
    if cd is None or research is None:
        return False, ""
    h = getattr(cd, "historicals_usd", None)
    rev = None
    if h is not None:
        label = h.ltm.label if h.ltm else (h.fy_labels[-1] if h.fy_labels else None)
        v = h.v("revenue", label) if label else None
        rev = v if v else None
    ok, share, how = qualifies(research, rev)
    if not ok:
        return False, ""
    return True, f"Shown because data centre or AI revenue is {share:.0%} of sales (above {AI_SHARE_THRESHOLD:.0%}): {how}."
