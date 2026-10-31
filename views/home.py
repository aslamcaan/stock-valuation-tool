"""Landing page: hero, company search, a tape of recent calls and the recent reports."""
from __future__ import annotations

import html
from datetime import date, timedelta

import streamlit as st
from streamlit_searchbox import st_searchbox

from core.cache import CacheMiss
from core.http import cache_key
from core.http import DataSourceError
from datasources.search import label, search
from datasources.tiingo import BASE as TIINGO
from desks.pipeline import load
from engine.history_multiples import split_adjusted_closes
from ui.format import money, when
from ui.hero import hero_svg
from ui.state import get_services
from ui.theme import ACCENT, BORDER, FAINT, FONT, MUTED, SURFACE, SURFACE_2, TEXT, VERDICT_COLOUR, dot

svc = get_services()
try:
    reports = svc.store.recent_reports(40)
except Exception as exc:  # a database problem should not hide the search
    reports = []
    st.warning(f"Could not load saved reports: {exc}")
latest: dict[str, dict] = {}
versions: dict[str, int] = {}
for r in reports:  # newest first: keep each company's latest report, count the earlier versions
    latest.setdefault(r["ticker"], r)
    versions[r["ticker"]] = versions.get(r["ticker"], 0) + 1

# Fallback when no report has a cached price series: a decorative line (an illustration, not data): it draws itself, an orange band marks a value range, a dot pulses.
CHART = """<svg class='chart' viewBox='0 0 800 300' preserveAspectRatio='none' aria-hidden='true'>
<defs><linearGradient id='vtg' x1='0' y1='0' x2='0' y2='1'><stop offset='0' stop-color='#ff7a1a' stop-opacity='.28'/>
<stop offset='1' stop-color='#ff7a1a' stop-opacity='0'/></linearGradient></defs>
<rect class='fvl' x='0' y='92' width='800' height='46' fill='rgba(255,122,26,.07)'/>
<line class='fvl' x1='0' y1='115' x2='800' y2='115' stroke='#ff7a1a' stroke-opacity='.55' stroke-dasharray='4 6'/>
<path class='area' d='M0 250 L60 238 L110 244 L170 214 L220 222 L280 190 L330 200 L390 168 L440 176 L500 140 L550 152
L610 120 L660 132 L720 96 L770 104 L800 88 L800 300 L0 300 Z' fill='url(#vtg)'/>
<path class='line' d='M0 250 L60 238 L110 244 L170 214 L220 222 L280 190 L330 200 L390 168 L440 176 L500 140 L550 152
L610 120 L660 132 L720 96 L770 104 L800 88' fill='none' stroke='#ff7a1a' stroke-width='2.5' stroke-linejoin='round'/>
<circle class='halo' cx='770' cy='104' r='6' fill='#ff7a1a'/><circle class='dot' cx='770' cy='104' r='5' fill='#ffd2ad'/>
</svg>"""



@st.cache_data(show_spinner=False, max_entries=20)
def hero_data(report_id: str, ticker: str, created: str) -> dict | None:
    """The report's last year of daily closes, from the cache its own run filled (never the network), with its
    fair value and DCF bear-to-bull range."""
    cache = get_services().cache
    day = date.fromisoformat(created[:10])
    hit = None
    for d in (day, day - timedelta(days=1)):  # the run's valuation date can sit a day before its UTC timestamp
        start = (d - timedelta(days=365 * 6 + 30)).isoformat()
        hit = cache.read("price", cache_key(f"{TIINGO}tiingo/daily/{ticker}/prices", {"startDate": start}),
                         allow_stale=True)
        if hit is not None and hit.payload:
            break
    if hit is None or not hit.payload:
        return None
    closes = sorted(split_adjusted_closes(hit.payload).items())
    cut = (date.fromisoformat(closes[-1][0]) - timedelta(days=365)).isoformat()
    closes = [(d, c) for d, c in closes if d >= cut]
    try:
        m = load(report_id, get_services().store).model
    except Exception:
        return None
    if m is None or m.verdict.fair_value is None or len(closes) < 20:
        return None
    band, v = None, m.valuation
    if v is not None and len(v.scenarios) == 3:
        b, bu = v.per_us_share(v.scenarios[0].value_per_share), v.per_us_share(v.scenarios[2].value_per_share)
        band = (min(b, bu), max(b, bu)) if None not in (b, bu) else None
    return {"closes": closes, "fair_value": m.verdict.fair_value, "band": band, "ticker": ticker,
            "to": closes[-1][0], "fetched": hit.fetched_at_iso[:10]}


hero = None
for r in list(latest.values())[:5]:  # the newest report whose price series is cached
    hero = hero_data(r["report_id"], r["ticker"], r["created_at"])
    if hero:
        break
if hero:
    CHART = hero_svg(hero["closes"], hero["fair_value"], hero["band"])
    CHART += (f"<div class='src'>{html.escape(hero['ticker'])} · daily close to {html.escape(when(hero['to']))} "
              f"(Tiingo, fetched {html.escape(when(hero['fetched']))}) · <span>fair value "
              f"{html.escape(money(hero['fair_value']))}</span>" + (" · band: DCF bear to bull" if hero["band"] else "")
              + "</div>")

try:
    rows = svc.edgar.company_tickers().payload
except (DataSourceError, CacheMiss) as exc:
    rows = None
    st.error(f"Could not load the SEC company list: {exc}")
facts = [(f"{len(rows):,}" if rows else "–", "SEC-listed companies to search"), ("8", "desks per report"),
         (str(len(latest)), "companies valued here")]
st.markdown(
    f"<div class='vt-hero'>{CHART}<div class='copy'><h1>Stock Valuation Tool</h1>"
    "<p>Sell-side style research and valuation for US-listed companies, built from the filings up. Every figure "
    "traces to a dated filing or market source; AI reads and writes, Python does the maths.</p><div class='facts'>"
    + "".join(f"<div><b>{html.escape(a)}</b>{html.escape(b)}</div>" for a, b in facts) + "</div></div></div>",
    unsafe_allow_html=True)

if latest:  # a tape of the latest calls; pauses on hover
    items = []
    for r in list(latest.values())[:14]:
        head = r["headline"] or ""
        verdict = next((v for v in VERDICT_COLOUR if head.startswith(v)), None)
        items.append(f"<span><b>{html.escape(r['ticker'])}</b>{dot(VERDICT_COLOUR.get(verdict, MUTED))}"
                     f"{html.escape(head)}</span>")
    st.markdown(f"<div class='vt-tape' aria-label='Latest calls'><div class='run'>{''.join(items * 2)}</div></div>",
                unsafe_allow_html=True)

_, mid, _ = st.columns([1, 2.2, 1])
with mid:
    if rows is None:
        st.stop()

    def _search(term: str) -> list[tuple[str, dict]]:
        return [(label(m), m) for m in search(rows, term, limit=10)]

    # the searchbox renders in its own frame, so the page CSS cannot reach it: the theme goes in as react-select styles
    field = {"fontFamily": FONT, "fontSize": "15px"}
    look = {
            "dropdown": {"fill": ACCENT, "rotate": True},
            "clear": {"fill": MUTED},
            "searchbox": {"control": {**field, "backgroundColor": SURFACE, "border": f"1px solid {BORDER}",
                                      "borderRadius": "10px", "boxShadow": "none", "minHeight": "44px"},
                          "input": {**field, "color": TEXT}, "singleValue": {**field, "color": TEXT},
                          "placeholder": {**field, "color": FAINT},
                          "menuList": {**field, "backgroundColor": SURFACE_2},
                          "option": {"color": TEXT, "backgroundColor": SURFACE_2, "highlightColor": "rgba(255,122,26,.18)"}}}
    picked = st_searchbox(_search, label="Stock name or ticker", placeholder="Company or ticker, e.g. UBER, Coca-Cola",
                          key="company_search", style_overrides=look)
    if picked:
        st.session_state["selected"] = picked
    picked = st.session_state.get("selected")
    if picked:
        st.markdown(f"**{label(picked)}**")
        if st.button("Run the report", type="primary", width="stretch", icon=":material/play_arrow:",
                     help="Runs all eight desks: data, checks, research, news, modelling, review, impact and MD "
                          "(a few minutes)."):
            st.session_state.start_ticker = picked["ticker"]
            st.switch_page("views/report.py")

st.subheader("Recent reports")
if not reports:
    st.caption("No reports yet. Completed reports appear here and open instantly, at no API cost.")


def _card(r: dict) -> None:
    head = r["headline"] or ""
    verdict = next((v for v in VERDICT_COLOUR if head.startswith(v)), None)
    rest = head[len(verdict):].strip() if verdict else head
    n = versions[r["ticker"]] - 1
    with st.container(border=True, key=f"card_{r['report_id']}"):
        st.markdown(
            f"<div class='vt-rc'><div class='top'><span class='t'>{html.escape(r['ticker'])}</span>"
            f"<span class='d'>{html.escape(when(r['created_at']))}</span></div>"
            f"<div class='h'>{dot(VERDICT_COLOUR.get(verdict, MUTED))}<b>{html.escape(verdict or 'Report')}</b> "
            f"{html.escape(rest)}</div>"
            + (f"<div class='d' style='margin-top:.3rem'>{n} earlier version{'s' if n != 1 else ''}</div>" if n else
               "<div class='d' style='margin-top:.3rem'>&nbsp;</div>")
            + "</div>", unsafe_allow_html=True)
        if st.button("Open", key=f"open_{r['report_id']}", width="stretch", icon=":material/arrow_forward:",
                     help=f"Report {r['report_id']}: {r['ticker']} {head}"):
            st.session_state.open_id = r["report_id"]
            st.switch_page("views/report.py")


cards = list(latest.values())[:12]
for i in range(0, len(cards), 3):
    cols = st.columns(3)
    for col, r in zip(cols, cards[i:i + 3]):
        with col:
            _card(r)
