"""How it works: the eight desks in the order a report runs, the rules every number follows, and how a rating is
scored (weights and cut points read from engine.rubric, so the page cannot drift from the code)."""
from __future__ import annotations

import streamlit as st

from engine.rubric import AI_CRITERIA, CODE_CRITERIA, LABELS, RATING_CUTS, WEIGHTS
from ui.run_panel import DESK_INFO
from ui.theme import ICON, RATING_COLOUR, esc

SOURCES = {
    "Data desk": ["SEC EDGAR XBRL", "FMP", "FRED FX", "Tiingo"],
    "Data checks": ["Code only"],
    "Research desk": ["Annual report", "AI reads, quotes verified"],
    "News desk": ["Web search", "Dated and verified"],
    "Modelling desk": ["Damodaran industry data", "Peers from SEC frames", "XBRL segment notes", "Code only"],
    "Review desk": ["AI", "Sees results, not opinions"],
    "Impact analyst": ["AI sizes, code prices", "S&P 500 and sector ETF"],
    "MD": ["AI judgement", "Number guard"],
}

st.title("How it works")
st.caption("A report is built by eight desks, in this order. Code does every calculation; AI reads filings and "
           "news, challenges the assumptions and writes the view.")

steps = "".join(
    f"<div class='vt-step' style='animation-delay:{i * .07:.2f}s'><div class='n'>{i + 1}</div><div><h6>{esc(d)}</h6>"
    f"<p>{esc(info)}</p><div class='k'>" + "".join(f"<span class='vt-tag'>{esc(s)}</span>" for s in SOURCES.get(d, []))
    + "</div></div></div>" for i, (d, info) in enumerate(DESK_INFO.items()))
st.markdown(f"<div class='vt-steps'>{steps}</div>", unsafe_allow_html=True)

st.subheader("Rules every number follows")
RULES = [
    ("AI never calculates", "All arithmetic is Python. The AI desks only read, judge and write."),
    ("Every number traces to a source", "Hover a figure in the report for its filing, XBRL tag, date and fetch time, "
                                        "or its formula and inputs."),
    ("Hard stops refuse to value", "A balance sheet out by more than 0.5%, a market cap more than 3% from FMP's, or "
                                   "terminal growth at or above WACC stops the report and names the line."),
    ("Numbers in AI text are checked", "Every figure the AI writes is matched against the computed results. A sentence "
                                       "that fails twice is dropped and logged."),
    ("Fetched text is data, not instructions", "Filings, news and web pages can be quoted with source and date, but "
                                               "they never steer the desks."),
    ("No opinions in", "The AI desks never see the user's view of a stock; temperature is 0 and outputs are validated "
                       "against a schema."),
]
st.markdown("<div class='vt-rules'>" + "".join(f"<div>{ICON['check']}<b>{esc(a)}</b>{esc(b)}</div>" for a, b in RULES)
            + "</div>", unsafe_allow_html=True)

st.subheader("How a rating is scored")
st.caption("Nine criteria, each scored 1 to 5. Code scores four from the model; the MD scores five with cited "
           "evidence. The weighted score maps to a rating, and the MD may move it one notch with a written reason. The "
           "rating cannot point against the valuation: an Overvalued verdict caps it at Hold and an Undervalued one "
           "floors it at Hold.")


def rows(criteria: list[str], by: str) -> str:
    return "".join(
        f"<div class='row'><span class='k'>{esc(LABELS[c])}<small>{esc(by)}</small></span><span class='bar'>"
        f"<i style='width:{WEIGHTS[c] / 0.25 * 100:.0f}%;animation-delay:{i * .06:.2f}s'></i></span>"
        f"<span class='s'>{WEIGHTS[c]:.0%}</span></div>" for i, c in enumerate(criteria))


bands, upper = [], 5.0
for cut, name in RATING_CUTS:
    bands.append((name, f"{cut:.1f} to {upper:.1f}"))
    upper = cut
bands.append(("Strong Sell", f"1.0 to {upper:.1f}"))
legend = "".join(f"<div class='row' style='grid-template-columns:1fr auto'><span class='k' style='color:"
                 f"{RATING_COLOUR[n]};font-weight:600'>{esc(n)}</span><span class='s'>{esc(r)}</span></div>"
                 for n, r in bands)
st.markdown(f"<div class='vt-why'><div class='vt-panel'><h6>Criteria and weights</h6><div class='vt-rubric'>"
            f"{rows(CODE_CRITERIA, 'code')}{rows(AI_CRITERIA, 'MD')}</div></div>"
            f"<div class='vt-panel'><h6>Weighted score to rating</h6><div class='vt-rubric'>{legend}</div></div></div>",
            unsafe_allow_html=True)
