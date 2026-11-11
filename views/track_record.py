"""Track Record: every call the tool has made, centred on the rating and the reasons for it. Each card also carries a
small since-the-call line (price change vs the S&P 500), computed by engine.track."""
from __future__ import annotations

from datetime import date, timedelta

import streamlit as st

from desks.pipeline import load
from engine.history_multiples import price_on_or_before
from engine.track import evaluate
from ui.format import money, when
from ui.state import get_services
from ui.theme import ACCENT, FAINT, GREEN, MUTED, RATING_COLOUR, RATINGS, RED, TEXT, VERDICT_COLOUR, esc, note

svc = get_services()
st.title("Track Record")
st.caption("Every report that reached a verdict, with the MD's rating and the reasons behind it. Hover a reason for "
           "the full text; open a call to see the whole report.")
calls = svc.store.calls()
if not calls:
    st.markdown(note("No completed reports yet. Every report that reaches a verdict is logged here automatically."),
                unsafe_allow_html=True)
    st.stop()


@st.cache_data(show_spinner=False, max_entries=200)
def reasons(report_id: str) -> dict:
    """The MD's summary lines and rubric score for one saved report (empty if it has none or cannot be read)."""
    try:
        rep = load(report_id, get_services().store)
    except Exception:  # an unreadable or deleted report still shows its logged call
        return {}
    md = getattr(rep, "md", None)
    if not md:
        return {"name": rep.company.profile.name if rep.company else ""}
    return {"name": rep.company.profile.name if rep.company else "", "lines": list(md.view.get("reasoning_lines") or []),
            "score": md.weighted_score, "code_rating": md.code_rating, "thesis": md.view.get("thesis", "")}


def rating_of(c: dict) -> str:
    return c.get("rating") or "Not rated"


# --- rating distribution, over every call ---------------------------------------------------------------------------
latest_only = st.toggle("Latest call per company only", value=True,
                        help="Off: every dated version, so you can see how a company's rating changed between runs.")
pool = calls
if latest_only:
    seen: set[str] = set()
    pool = [c for c in calls if not (c["ticker"] in seen or seen.add(c["ticker"]))]
groups = RATINGS + ["Not rated"]
counts = {g: sum(1 for c in pool if rating_of(c) == g) for g in groups}
total = sum(counts.values())
segs = "".join(
    f"<div style='flex:{n};background:{RATING_COLOUR.get(g, '#3d342c')};"
    f"{'color:' + TEXT + ';' if g == 'Not rated' else ''}animation-delay:{i * .08:.2f}s' title='{esc(g)}: {n}'>"
    f"{esc(g)} · {n}</div>" for i, (g, n) in enumerate(counts.items()) if n)
st.markdown(f"<div class='vt-dist' role='img' aria-label='Ratings: "
            + esc(", ".join(f"{g} {n}" for g, n in counts.items() if n)) + f"'>{segs}</div>"
            f"<div class='vt-muted'>{total} call{'s' if total != 1 else ''} across "
            f"{len({c['ticker'] for c in pool})} companies</div>", unsafe_allow_html=True)

c1, c2 = st.columns([3, 2], vertical_alignment="bottom")
chosen = c1.pills("Rating", [g for g in groups if counts[g]], selection_mode="multi", key="tr_ratings")
tickers = c2.multiselect("Company", sorted({c["ticker"] for c in pool}), placeholder="All companies")
shown = [c for c in pool if (not chosen or rating_of(c) in chosen) and (not tickers or c["ticker"] in tickers)]
if not shown:
    st.markdown(note("No calls match these filters."), unsafe_allow_html=True)
    st.stop()

# --- since the call (optional, small): one cached price series per ticker, plus the S&P 500 --------------------
show_since = st.toggle("Show the price move since each call", value=False,
                       help="Fetches daily closes for each company and the S&P 500 (cached for six hours).")
start = (min(date.fromisoformat(c["call_date"]) for c in shown) - timedelta(days=10)).isoformat()


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def closes(ticker: str, start_: str) -> dict:
    try:
        r = get_services().market.price_history(ticker, start_)
        return {x["date"]: x["close"] for x in r.data} if r.available else {}
    except Exception:  # prices are a footnote here: a failed fetch leaves the line out
        return {}


def price_at(ticker: str, when_: date) -> float | None:
    return price_on_or_before(closes(ticker, start), when_, max_gap_days=7) if show_since else None


with st.spinner("Fetching prices…" if show_since else "Loading the calls…"):
    results = [evaluate(c, price_at, date.today()) for c in shown]


# --- price 1, 3 and 6 months later, against the price and the base DCF at the call -------------------------------
@st.cache_data(show_spinner=False, max_entries=200)
def base_dcf(report_id: str) -> float | None:
    """The report's base-case DCF per US share (older saved reports without the figures fall back to the DCF itself)."""
    try:
        rep = load(report_id, get_services().store)
        v = rep.model.valuation if rep.model else None
        if v is None or v.dcf is None:
            return None
        return (getattr(v, "dcf_figures", None) or {}).get("base") or v.per_us_share(v.dcf.value_per_share)
    except Exception:  # an unreadable report just has no base DCF in the table
        return None


def horizons_section() -> None:
    from engine.track import AFTER, hit_rate_by_rating, horizon_row
    from ui.format import plain_table
    if not st.toggle("Show the price 1, 3 and 6 months after each call", value=True, key="tr_horizons",
                     help="Fetches daily closes (cached for six hours). A column stays empty until that date has passed."):
        return
    start_h = (min(date.fromisoformat(c["call_date"]) for c in shown) - timedelta(days=10)).isoformat()

    def px(ticker: str, when_: date) -> float | None:
        return price_on_or_before(closes(ticker, start_h), when_, max_gap_days=7)
    with st.spinner("Fetching prices…"):
        rows = [horizon_row(c, px, date.today(), base_dcf(c["report_id"])) for c in shown]

    def cell(a: dict) -> str:
        if not a["elapsed"]:
            return "not yet"
        if a["price"] is None:
            return "no price"
        hit = {True: " ✓", False: " ✗", None: ""}[a["hit"]]
        gap = "" if a["vs_base_dcf"] is None else f" ({a['vs_base_dcf']:+.0%} vs base DCF)"
        return f"{money(a['price'])} {a['change']:+.0%}{hit}{gap}" if a["change"] is not None else money(a["price"])
    head = ["Call", "Ticker", "Rating", "Verdict", "Price", "Base DCF"] + [f"After {h}" for h in AFTER]
    body = [[r["call_date"], r["ticker"], r["rating"], r["verdict"] or "–", money(r["price"]) if r["price"] else "–",
             money(r["base_dcf"]) if r["base_dcf"] else "–"] + [cell(r["after"][h]) for h in AFTER] for r in rows]
    st.markdown("#### Price after the call")
    st.markdown(plain_table(body, head), unsafe_allow_html=True)
    rates = hit_rate_by_rating(rows)
    if rates:
        order = [g for g in RATINGS if g in rates]
        hr = [[g] + [("–" if rates[g][h]["rate"] is None else f"{rates[g][h]['rate']:.0%} of {rates[g][h]['calls']}")
                     for h in AFTER] for g in order]
        st.markdown("#### Hit rate by rating")
        st.markdown(plain_table(hr, ["Rating"] + [f"After {h}" for h in AFTER]), unsafe_allow_html=True)
    st.caption("✓ means the price moved the way the rating said: up for a Buy or Strong Buy, down for a Sell or Strong "
               "Sell, within 10% either way for a Hold. Prices are daily closes (FMP or Tiingo) on or before the date, "
               "against the price at the call. Small samples: a hit rate on a handful of calls is not evidence.")


horizons_section()


def mini(price: float, fv: float) -> str:
    """Price at the call against the call's fair value, on one small axis."""
    lo, hi = min(price, fv), max(price, fv)
    pad = (hi - lo) * 0.35 or hi * 0.1
    a, b = lo - pad, hi + pad

    def x(v):
        return (v - a) / (b - a) * 100
    colour = GREEN if fv > price else RED
    pl, fl = ("r", "l") if price < fv else ("l", "r")  # labels point inward, so they stay inside the card
    return (f"<div class='vt-mini' role='img' aria-label='Price {esc(money(price))}, fair value {esc(money(fv))}'>"
            f"<div class='tr'></div><div class='gap' style='left:{x(lo):.1f}%;width:{x(hi) - x(lo):.1f}%;"
            f"background:{colour};opacity:.35'></div>"
            f"<div class='m' style='left:{x(price):.1f}%;background:{TEXT}'></div>"
            f"<div class='m' style='left:{x(fv):.1f}%;background:{ACCENT}'></div>"
            f"<div class='lb {pl}' style='left:{x(price):.1f}%;color:{MUTED}'>price {esc(money(price))}</div>"
            f"<div class='lb {fl}' style='left:{x(fv):.1f}%;color:{ACCENT}'>fair value {esc(money(fv))}</div></div>")


def card(r) -> None:
    c = r.call
    info = reasons(c["report_id"])
    rating = rating_of(c)
    rc = RATING_COLOUR.get(rating, FAINT)
    vc = VERDICT_COLOUR.get(c["verdict"], MUTED)
    gap = c["fair_value"] / c["price"] - 1 if c.get("price") and c.get("fair_value") else None
    lines = info.get("lines") or []
    why = ("<ul class='why'>" + "".join(f"<li title='{esc(x)}'>{esc(x)}</li>" for x in lines[:3]) + "</ul>") if lines \
        else f"<div class='vt-muted'>{'The AI desks did not run for this report, so there are no MD reasons.' if rating == 'Not rated' else 'No summary lines saved with this report.'}</div>"
    since = []
    if r.ret is not None:
        since.append(f"since call <b style='color:{GREEN if r.ret >= 0 else RED}'>{r.ret:+.1%}</b>")
        if r.spy_ret is not None:
            since.append(f"S&amp;P 500 <b>{r.spy_ret:+.1%}</b>")
    foot = [f"conviction <b>{esc(c.get('conviction') or '–')}</b>", f"confidence <b>{esc(c.get('confidence') or '–')}</b>",
            f"<b>{esc((c.get('stage') or c.get('toolkit') or '').replace('_', ' '))}</b>"] + since
    score = f" · rubric {info['score']:.2f}/5" if info.get("score") is not None else ""
    with st.container(border=True, key=f"card_{c['report_id']}"):
        st.markdown(
            f"<div class='vt-call'><div class='hd'><div><div class='tk'>{esc(c['ticker'])}</div>"
            f"<div class='nm'>{esc(info.get('name') or '')} · {esc(when(c['call_date'] + 'T' + c['call_time'] + ':00+00:00'))}</div></div>"
            f"<span class='vt-pill' style='color:{rc};border-color:{rc}66;background:{rc}14'>{esc(rating)}</span></div>"
            f"<div class='vd'><b style='color:{vc}'>{esc(c['verdict'] or '–')}</b>"
            + (f" · fair value {gap:+.1%} vs the price at the call" if gap is not None else "") + f"{esc(score)}</div>"
            + (mini(c["price"], c["fair_value"]) if gap is not None else "") + why
            + f"<div class='ft'>{''.join(f'<span>{x}</span>' for x in foot if x)}</div></div>", unsafe_allow_html=True)
        if st.button("Open report", key=f"tr_open_{c['report_id']}", icon=":material/arrow_forward:"):
            st.session_state.open_id = c["report_id"]
            st.switch_page("views/report.py")


for i in range(0, len(results), 2):
    cols = st.columns(2)
    for col, r in zip(cols, results[i:i + 2]):
        with col:
            card(r)
st.caption("Since-call figures compare the latest close with the price at the call (FMP or Tiingo daily closes) and "
           "are shown for context only; the tool is judged on its reasoning, not on short-term price moves.")
