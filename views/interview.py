"""Talking points: how to explain the tool in an interview. The pitch and the decisions are fixed text; the worked
example is read from a saved report (ui.talking), so every figure quoted is one the report shows, with its date."""
from __future__ import annotations

import streamlit as st

from desks.pipeline import load
from ui.format import money, pct, plain_table, when
from ui.talking import example, fmt_regression, pitch, test_count
from ui.theme import esc, guide, note
from ui.state import get_services

svc = get_services()


def html(s: str) -> None:
    st.markdown(s, unsafe_allow_html=True)


def kv(items: list[tuple[str, str, str]], accent: int | None = None) -> str:
    return "<div class='vt-kv'>" + "".join(
        f"<div><div class='l'>{esc(a)}</div><div class='v{' acc' if k == accent else ''}'>{esc(b)}</div>"
        f"<div class='s'>{esc(c)}</div></div>" for k, (a, b, c) in enumerate(items)) + "</div>"


def qa(items: list[tuple[str, str]]) -> None:
    for q, a in items:
        with st.expander(q):
            st.markdown(a)


st.title("Talking points")
st.caption("How to explain this tool in an interview: the short version, a worked example from a saved report, the "
           "decisions behind it and the questions to expect.")
html(guide("Read top to bottom before an interview. The worked example is built from the saved report you pick, so its "
           "numbers match the report exactly and carry its date. Open a question to see the answer.", "How to use this"))

# --- 1. the short version --------------------------------------------------------------------------------------------
st.subheader("The 30-second version")
n_tests = test_count()
st.markdown(
    "I built an equity research tool that values a US-listed company from its SEC filings. Eight desks run in order, "
    "like a research team: code fetches and checks the data, builds the forecast and runs every valuation method; AI "
    "reads the annual report and the news, challenges the assumptions and writes the view; code checks every number "
    "the AI writes. **The AI never calculates**: all arithmetic is Python, and every figure traces to a filing, an "
    "XBRL tag and a fetch date.")
html(kv([("Desks", "8", "data, checks, research, news, modelling, review, impact, MD"),
         ("Data sources", "6", "SEC EDGAR, FMP, FRED, Damodaran, Tiingo, Finnhub"),
         ("Valuation methods", "DCF + 4", "comps, own history, sum of the parts, reverse DCF; sector toolkits"),
         ("Offline tests", f"{n_tests:,}" if n_tests else "–", "test functions on recorded API responses, no network")]))

# --- 2. worked example -----------------------------------------------------------------------------------------------
st.subheader("Worked example")


@st.cache_resource(show_spinner=False, max_entries=16)
def _example(report_id: str):
    return example(load(report_id, svc.store))


try:
    rows = svc.store.recent_reports(80)
except Exception as exc:  # noqa: BLE001 - the rest of the page still works
    rows = []
    st.caption(f"Saved reports could not be loaded: {exc}")
latest: dict[str, dict] = {}
for r in rows:
    latest.setdefault(r["ticker"], r)
if not latest:
    html(note("No saved reports yet. Run one from the Search page and it will appear here."))
else:
    tickers = list(latest)
    pick = st.selectbox("Company", tickers, index=tickers.index("KO") if "KO" in tickers else 0,
                        format_func=lambda t: f"{t} · report of {when(latest[t]['created_at'])}")
    x = _example(latest[pick]["report_id"])
    if x is None:
        html(note(f"{pick} is valued with a bank, insurer or REIT toolkit (no DCF), so there is no walk to the price. "
                  "Pick a corporate company for the worked example; the answer on financials is under the questions "
                  "below."))
    else:
        st.markdown(pitch(x))
        html(kv([("Price", money(x["price"]), f"{x['price_source']} · {when(x['price_date'])[:11].strip(', ')}"),
                 ("Fair value", money(x["fair_value"]), "blend of the methods"),
                 ("Verdict", x["verdict"] or "–", "fair value vs price" if x["gap"] is None else f"{x['gap']:+.1%} upside"),
                 ("Rating", x["rating"] or "–", f"conviction {x['conviction']}" if x["conviction"] else ""),
                 ("DCF", money(x["dcf"]), f"WACC {pct(x['wacc'])}; terminal value {x['tv_share']:.0%} of EV")], accent=1))
        st.markdown("**Say it with the walk**: one assumption at a time, from our DCF to the price.")
        html(plain_table([[s["label"], "–" if k == 0 else f"{s['change']:+,.2f}", money(s["value"]), s["detail"]]
                          for k, s in enumerate(x["walk"])], ["Step", "Change", "Value per share", "What changed"]))
        points = []
        if "split" in x:
            sp = x["split"]
            points.append(f"**What the price pays for.** With no growth at all the business is worth "
                          f"US${sp['no_growth_ev'] / 1000:,.1f}bn. Growth is {sp['growth_ours']:.0%} of our enterprise "
                          f"value and {sp['growth_market']:.0%} of the market's." if sp["growth_ours"] >= 0 else
                          f"**What the price pays for.** In our DCF, growth subtracts value (reinvestment earns less "
                          f"than WACC); the market prices {sp['growth_market']:.0%} of its enterprise value as growth.")
        if "mc" in x:
            mc = x["mc"]
            points.append(f"**How sure is the DCF?** Across {mc['n']:,} versions with growth, margin, WACC and terminal "
                          f"growth varied, the middle 80% runs {money(mc['p10'])} to {money(mc['p90'])} (median "
                          f"{money(mc['p50'])}); {mc['above']:.0%} of them are above the price.")
        if "regression" in x:
            points.append("**Multiples adjusted for quality.** " + fmt_regression(x["regression"]))
        if x["gate_note"]:
            points.append(f"**Rating gate.** {x['gate_note']}")
        for p in points:
            st.markdown("- " + p)
        st.caption(f"All figures from the saved {x['ticker']} report of {when(x['created_at'])}. Open it from the "
                   "Search page to show the charts behind each line.")

# --- 3. decisions -----------------------------------------------------------------------------------------------------
st.subheader("The decisions, and why")
html(guide("Interviewers ask why more than what. Each answer is one design choice and the reason for it.", "Why these"))
qa([
    ("Why does AI never do arithmetic?",
     "Language models are good at reading and judging, unreliable at calculating. So code does every sum, and the AI "
     "desks only read filings and news, score qualitative criteria and write. A **number guard** checks every figure in "
     "AI text against the computed results (allowing rounding and units, e.g. \"$1.1bn\" matches 1,110m); a sentence "
     "that fails is regenerated once, then dropped and logged."),
    ("Why forecast operating income, not net income?",
     "Net income carries one-offs: tax settlements, investment gains, impairments. The DCF starts from operating "
     "income, cleaned of one-off items the research desk reads from three annual reports, and flags any year where net "
     "income is far above operating income."),
    ("Why can't the rating say Buy when the stock looks overvalued?",
     "An early version did: the rubric scored quality highly and produced Buy on stocks the valuation called "
     "overvalued. Now an Overvalued verdict caps the rating at Hold and an Undervalued one floors it at Hold, and the "
     "report says when the gate moved the rating."),
    ("Why refuse to value some companies?",
     "**Hard stops**: if the balance sheet does not balance within 0.5%, or the computed market cap is more than 3% "
     "from FMP's, the data is wrong somewhere, and a confident number on bad data is worse than none. The report names "
     "the line that broke. Smaller issues (lines not summing within 1%, EDGAR and FMP disagreeing by more than 2%) "
     "are flags, not stops, because XBRL coverage is patchy."),
    ("Why not a DCF for banks, insurers and REITs?",
     "For a bank, debt and deposits are the raw material of the business, so free cash flow and WACC lose their "
     "meaning. Banks and insurers use justified price-to-book (return on equity against the cost of equity), residual "
     "income, a dividend model and peer multiples; REITs use net asset value and price to FFO."),
    ("Why show the walk to the price instead of just the fair value?",
     "A fair value far below the price invites the question \"so the market is wrong?\". The walk answers it: it "
     "separates the forecast (margins, tax, returns, growth) from the required return, and usually shows the market "
     "is pricing a lower discount rate rather than a better business."),
])

# --- 4. questions to expect ------------------------------------------------------------------------------------------
st.subheader("Questions to expect")
qa([
    ("\"Your value is far below the analysts'. Who's right?\"",
     "Neither number is a forecast of the price. Analysts' targets mostly apply a multiple the stock already trades on, "
     "so they assume the market's pricing is about right; the DCF tests it against a required return built from the "
     "risk-free rate, beta and the equity risk premium. The walk shows how much of the gap is conventions and how much "
     "is the discount rate. I'd say the price implies a lower required return than the model uses, which is a "
     "judgement the user can make, not an error."),
    ("\"How do you know the numbers are right?\"",
     "Four layers. The data is cross-checked (EDGAR against FMP on revenue, net income, cash, debt and shares), and the "
     "XBRL tag used for each number is logged. Hard stops and flags catch broken statements. The engine is pure Python "
     f"with {n_tests or 'several hundred'} offline tests on recorded API responses, including a whole report run "
     "offline. Every number on screen can be hovered for its source, tag and fetch date."),
    ("\"How did you build the WACC?\"",
     "Risk-free rate from FRED's 10-year Treasury; an industry unlevered beta from Damodaran, relevered at the "
     "company's market debt-to-equity; times Damodaran's implied equity risk premium; plus country risk weighted by "
     "where the company earns its revenue. Cost of debt from a synthetic rating on interest cover. The report shows "
     "each input with its date."),
    ("\"What's the weakest part?\"",
     "The Monte Carlo draws its inputs independently, while in reality growth and margins move together, so its range "
     "is probably too narrow. The peer regressions run on five to eight peers, so they are a cross-check, not part of "
     "the fair value. And it covers US-listed companies only, because it depends on SEC filings."),
    ("\"Where does AI actually add value?\"",
     "Reading: segments, one-off items, risks and KPIs from a 100-page annual report, with every quote checked against "
     "the filing text. Judgement: the review desk challenges the weakest assumptions and writes the bear case, and the "
     "MD scores moat, management and governance with cited evidence. A full report costs about US$0.15-0.50 of AI."),
    ("\"What would you build next?\"",
     "Correlated inputs in the Monte Carlo; non-US filers through IFRS filings in other markets; and a longer track "
     "record, so the calls can be scored against what the price did afterwards (the Track Record page already logs "
     "each call with its date)."),
])

st.subheader("Show, don't tell")
st.markdown(
    "1. Search a company live and let the desks run (a minute or two).\n"
    "2. Header: price, fair value, verdict and how the rating was scored.\n"
    "3. Valuation tab: the walk from our DCF to the price, then the Monte Carlo range.\n"
    "4. Hover any figure in Financials to show its filing, XBRL tag and fetch time.\n"
    "5. What if: press \"Market's discount rate\" to show the DCF meeting the price.\n"
    "6. Download the Excel model: its formulas are live and its fair value equals the app's.")
