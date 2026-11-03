"""The public overview shown under the login form: what the tool does and in what order, with no thresholds, weights,
prompts or scoring rules (those stay behind the password)."""
from __future__ import annotations

import streamlit as st

from ui.theme import ICON, esc

DESKS = [
    ("Data desk", "Ten years of filings from SEC EDGAR, with prices and exchange rates from dated sources, "
                  "cross-checked against a second provider.", ["SEC EDGAR", "Dated sources"]),
    ("Data checks", "The balance sheet must balance and the cash flow must tie. If a hard check fails, the tool refuses "
                    "to value the company and names the line that broke.", ["Code only"]),
    ("Research desk", "AI reads the latest annual report for segments, one-off items and risks. Every quote is checked "
                      "against the filing text.", ["AI reads", "Quotes verified"]),
    ("News desk", "Searches recent news and drops anything undated, stale or unverifiable.", ["Dated and verified"]),
    ("Modelling desk", "Forecast, discount rate, DCF, scenarios, peer multiples and sum of the parts, blended into one "
                       "fair value. All of the arithmetic is Python.", ["Code only"]),
    ("Review desk", "A second AI challenges the assumptions and writes the strongest bull and bear cases.",
     ["AI", "Sees results, not opinions"]),
    ("Impact analyst", "Sizes what each news item is worth and whether the share price has already moved.",
     ["AI sizes, code prices"]),
    ("MD", "Scores the case and gives a rating that never points against the valuation. Every number it quotes is "
           "checked against the model.", ["AI judgement", "Number guard"]),
]

PRINCIPLES = [
    ("AI never calculates", "All arithmetic is Python. The AI only reads, judges and writes."),
    ("Every number has a source", "Each figure traces to a filing and a date."),
    ("AI text is checked", "Every number the AI writes is matched against the computed results."),
]


def overview_html() -> str:
    steps = "".join(
        f"<div class='vt-step' style='animation-delay:{i * .07:.2f}s'><div class='n'>{i + 1}</div><div>"
        f"<h6>{esc(name)}</h6><p>{esc(text)}</p><div class='k'>"
        + "".join(f"<span class='vt-tag'>{esc(t)}</span>" for t in tags) + "</div></div></div>"
        for i, (name, text, tags) in enumerate(DESKS))
    rules = "".join(f"<div>{ICON['check']}<b>{esc(a)}</b>{esc(b)}</div>" for a, b in PRINCIPLES)
    return (f"<div class='vt-overview'><h2>How it works</h2><p class='vt-muted'>A report is built by eight desks, in "
            f"this order.</p><div class='vt-steps'>{steps}</div><div class='vt-rules'>{rules}</div></div>")


def show_overview() -> None:
    st.markdown(overview_html(), unsafe_allow_html=True)
