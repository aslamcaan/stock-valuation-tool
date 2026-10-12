"""Debug page: raw data for a chosen ticker from every source, with cache timestamps."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from core.cache import CacheMiss
from core.http import DataSourceError
from datasources.fmp import ENDPOINTS
from datasources.fred import FX_SERIES, SERIES
from ui.state import get_services

svc = get_services()
st.title("Debug: raw data")
st.caption("Raw responses as fetched and cached. Each block shows its fetch time and whether it came from cache.")


def _meta(c) -> None:
    st.caption(f"Fetched {c.fetched_at_iso} UTC · {'from cache' if c.from_cache else 'fresh fetch'}")


def _safe(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except (DataSourceError, CacheMiss) as exc:
        st.error(str(exc))
    return None


with st.expander("Settings (secrets redacted)"):
    st.json(svc.settings.redacted())

ticker = st.text_input("Ticker", value=st.session_state.get("selected", {}).get("ticker", "AAPL")).upper().strip()
if not ticker:
    st.stop()

tab_edgar, tab_fmp, tab_fred, tab_dam, tab_probe = st.tabs(
    ["SEC EDGAR", "FMP", "FRED", "Damodaran", "FMP endpoint check"])

with tab_edgar:
    cik = _safe(svc.edgar.cik_for, ticker)
    if cik is None:
        st.warning(f"{ticker} not found in SEC company_tickers_exchange.json")
    else:
        st.write(f"**CIK** {cik:010d}")
        sub = _safe(svc.edgar.submissions, cik)
        if sub:
            _meta(sub)
            p = sub.payload
            st.json({k: p.get(k) for k in ("name", "sic", "sicDescription", "fiscalYearEnd", "stateOfIncorporation",
                                           "category", "tickers", "exchanges", "entityType")})
            filings = svc.edgar.filings(cik, forms={"10-K", "20-F", "40-F", "10-Q", "6-K", "8-K"})
            st.dataframe(pd.DataFrame([f.__dict__ | {"url": f.url(cik)} for f in filings[:40]]), hide_index=True)
        facts = _safe(svc.edgar.companyfacts, cik)
        if facts:
            _meta(facts)
            fp = facts.payload["facts"]
            st.write("Taxonomies:", {k: len(v) for k, v in fp.items()})
            taxonomy = st.selectbox("Taxonomy", list(fp))
            tag = st.selectbox("Tag", sorted(fp[taxonomy]))
            units = fp[taxonomy][tag]["units"]
            unit = st.selectbox("Unit", list(units))
            df = pd.DataFrame(units[unit])
            st.dataframe(df.sort_values("end", ascending=False) if "end" in df else df, hide_index=True)

with tab_fmp:
    name = st.selectbox("Endpoint", list(ENDPOINTS), format_func=lambda n: f"{n} — {ENDPOINTS[n].purpose}")
    sym = "BZUSD" if name == "commodity_quote" else ticker
    if st.button("Fetch", key="fmp_fetch"):
        c = _safe(svc.fmp.call, name, sym)
        if c:
            _meta(c)
            data = c.payload
            if isinstance(data, list) and data and isinstance(data[0], dict):
                st.dataframe(pd.DataFrame(data), hide_index=True)
            else:
                st.json(data)

with tab_fred:
    series_id = st.selectbox("Series", list(SERIES) + [s for s, _ in FX_SERIES.values()],
                             format_func=lambda s: f"{s} — {SERIES.get(s, 'FX')}")
    c = _safe(svc.fred.series, series_id, start="2020-01-01")
    if c:
        _meta(c)
        df = pd.DataFrame(c.payload, columns=["date", "value"]).dropna()
        st.line_chart(df.set_index("date"))
        st.dataframe(df.tail(20), hide_index=True)

with tab_dam:
    erp = _safe(svc.damodaran.implied_erp)
    if erp:
        st.metric("Implied ERP", f"{erp.value:.2%}", help=erp.detail)
        st.caption(f"{erp.file} · as of {erp.as_of} · fetched {erp.fetched_at}")
    region = st.radio("Beta / margin region", ["us", "global", "emerging"], horizontal=True)
    res = _safe(svc.damodaran.industry_betas, region)
    if res:
        st.caption(f"Industry betas, as of {res[1]}")
        st.dataframe(pd.DataFrame(res[0]).T, height=250)
    res = _safe(svc.damodaran.industry_margins, region)
    if res:
        st.caption(f"Industry margins, as of {res[1]}")
        st.dataframe(pd.DataFrame(res[0]).T, height=250)
    res = _safe(svc.damodaran.country_risk)
    if res:
        st.caption(f"Country risk premiums, as of {res[1]}")
        st.dataframe(pd.DataFrame(res[0]).T, height=250)

with tab_probe:
    st.write("Calls every FMP endpoint the app uses (bypasses cache) for AAPL and GRAB.")
    if st.button("Run endpoint check"):
        with st.spinner("Calling FMP…"):
            rows = svc.fmp.probe()
        st.dataframe(pd.DataFrame(rows), hide_index=True)
