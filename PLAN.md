# PLAN.md — build progress

Source brief: `PROMPT.md`. Rules: `CLAUDE.md`. Tick items as they are completed so a new session can resume.

## Setup
- [x] CLAUDE.md with RULES, ACCURACY RULES and AI RULES (verbatim)
- [x] PLAN.md
- [x] git repo initialised, private GitHub repo `stock-valuation-tool` created and pushed

## RELEASE 1: core tool (corporate companies)

### Phase 1 — setup, fetchers, search, debug page
- [x] requirements.txt, .env.example, .gitignore (.env, cache, database excluded)
- [x] Config loader (.env / Streamlit secrets), never logs keys
- [x] Local response cache with timestamps and per-source TTLs (price 15m, estimates 1d, FRED 1d, filings/companyfacts 30d, Damodaran 30d, news ≤1h)
- [x] SEC EDGAR fetcher (tickers+exchange, companyfacts, submissions, filing documents), User-Agent from .env, ≤10 req/s
- [x] FMP fetcher with endpoint registry and availability probe
- [x] FRED fetcher (DGS10, FX, Brent/WTI)
- [x] Damodaran fetcher (implied ERP, country risk premiums, industry betas, industry margins)
- [x] Search bar ("Stock name or ticker") on landing page
- [x] Debug page showing raw data for a chosen ticker
- [x] Offline tests with fixtures; live tests marked `@pytest.mark.live`
- [x] Commit + push
- [x] **CHECKPOINT 1:** .env instructions → user adds keys → test connections → report unavailable FMP endpoints + alternatives

### Phase 2 — golden fixtures
- [x] Extract tests/fixtures/grab_model.xlsx → tests/fixtures/grab_expected.json (historicals, assumptions, value per share, cell refs)
- [x] tests/fixtures/uber_expected.json from the brief
- [x] Commit + push
- [ ] **CHECKPOINT 2:** show extracted Grab table, wait for confirmation

### Phase 3 — historicals and financial analysis
- [x] Historicals 5–10 years + LTM, US GAAP + IFRS tag mapping with fallbacks, tag logging
- [x] Value objects {value, currency, unit, period, source, tag, fetched_at}; unit normalisation
- [x] FX (FRED; period-average for IS/CF, period-end for BS), ADR ratios, currency-mismatch flag
- [x] Non-December fiscal years; restated figures; >120-day filing flag
- [x] Data checks: hard stops (BS balance >0.5%, market cap >3% vs FMP); red flags (sums, cash tie, 1%); EDGAR vs FMP amber (>2%)
- [x] Ratios and full financial analysis (Section 6 item 4, no Beneish/Altman)
- [x] Pass `test_grab_data` and Uber test
- [x] Commit + push

### Phase 4 — engine
- [x] Sector toolkit classification (SIC) and lifecycle stage; cycle percentile measurement
- [x] Consensus blending (history | consensus | industry | chosen, source, confidence)
- [x] Forecast by stage
- [x] WACC (DGS10, Damodaran ERP, relevered industry beta, revenue-weighted CRP, after-tax Kd, market weights)
- [x] DCF (SBC as cash cost, mid-year, stub, Gordon TV, g/ROIC reinvestment, equity bridge, treasury-method diluted shares)
- [x] SOTP, scenarios, sensitivity grids, reverse DCF
- [x] Pass `test_grab_engine`, KO and cyclical tests
- [x] Commit + push
- [x] **CHECKPOINT 3:** valuation summary for GRAB, KO, AAPL

### Phase 5 — comps, verdict, flags, provenance
- [x] Comps (peer filter SIC + 0.25–4x mcap, min 5), historical multiples, estimate revisions
- [x] Industry benchmarking percentiles
- [x] Verdict rules + confidence; flags; football field; assumptions table; provenance / click-to-trace
- [x] Pass `test_grab_judgement`, ASML, AAPL tests
- [ ] Commit + push

### Phase 6 — AI desks
- [x] Research desk (Haiku), review desk, MD (Sonnet); temperature 0; JSON schemas
- [x] Number guard; determinism; cost logging and caps
- [x] Pass determinism and number-guard tests
- [x] Commit + push

### Phase 7 — UI
- [x] Landing page, progress panel (threads + queue), full report, editable assumptions with live recalculation
- [x] Track Record page with auto-logging (SQLite)
- [x] Commit + push

### Phase 8 — exports
- [x] Excel export (banking conventions, real formulas); verify Grab file calculates, matches app
- [x] PDF report
- [x] Commit + push

### Phase 9 — README
- [x] README (architecture diagram, setup, tests, limitations); push
- [ ] **CHECKPOINT 4:** Release 1 summary + run command; wait for user

## RELEASE 2: news, ownership, comparison
- [x] Phase 10 — exposure profile, news desk (four tiers, freshness, source labels)
- [x] Phase 11 — impact analyst, priced-in, news-adjusted fair value, MD news summary, Refresh news, rubric feed
- [x] Phase 12 — ownership, Form 4, short interest, Beneish M, Altman Z
- [x] Phase 13 — Compare page
- [ ] **CHECKPOINT 5:** news demo on CVX and GRAB

## RELEASE 3: financial-sector toolkits
- [x] Phase 14 — bank toolkit; extract JPM expected values
- [ ] **CHECKPOINT 6:** JPM fixture confirmation (fixture built and independently verified; awaiting user review)
- [x] Phase 15 — insurance and REIT toolkits; pass JPM, O, TRV tests

## DEPLOY
- [ ] Phase 16 — password gate, secrets, hosted DB for Track Record
- [ ] **CHECKPOINT 7:** deployment walkthrough

## Notes / decisions log
- Packages: `core/` (config, cache, http, services), `datasources/` (EDGAR, FMP, FRED, Damodaran, search), `ui/` + `pages/` (Streamlit). Valuation engine will be its own pure package `engine/`.
- FMP uses the `/stable/` API. SEC search uses company_tickers_exchange.json (has exchange; company_tickers.json does not). OTC rows excluded.
- Landing search uses `streamlit-searchbox` so matches update per keystroke (st.text_input only updates on Enter).
- Tests: offline by default; `VT_OFFLINE=1` + `VT_CACHE_DIR` serves recorded cache entries, never the network. Live tests: `pytest -m live`.
- FMP has no estimate-history endpoint known on the stable API; plan: snapshot consensus daily ourselves for 30/60/90-day revisions (confirm at Checkpoint 1).
- Checkpoint 1 (2026-10-12): FRED OK; Anthropic OK (claude-haiku-5-5, claude-sonnet-5-5 available); Damodaran OK.
  FMP key is on the free plan: statements capped at limit=5; only a sample of large US symbols allowed
  (AAPL, UBER, KO, JPM, CVX, PEP, MSFT ok; GRAB, ASML, MU, SNDK, O, TRV, DASH, LYFT, SE blocked);
  news, insider-trading and institutional-ownership endpoints restricted.
  Decision: stay on free FMP while building; user will upgrade FMP before demos. `datasources/market.py`
  tries FMP first, then Tiingo (prices) and Finnhub (market cap, ratings, beat/miss, news, insiders), recording the
  reason. Analyst estimates and price targets have no free source: report says so and forecast uses history.
  Finnhub may quote a foreign company's home listing (ASML -> ASML.AS, EUR): market-cap check must convert currency.
  After the FMP upgrade: run Debug > Market data coverage for GRAB/ASML and confirm every item says FMP.
  SEC identity set; live tests (SEC, FRED, FMP, Tiingo/Finnhub, Damodaran) pass.
- Phase 2: Grab model is a single sheet 'GRAB DCF' (5-year DCF, end-of-year discounting, no stub, no SBC, no NWC,
  EV + cash & investments - debt, 4,100m shares). Extractor: scripts/extract_grab_model.py (re-run if the model changes).
  Engine needs convention switches (end-year vs mid-year, stub on/off, SBC on/off, NWC on/off) to reproduce it.
- Phase 3: convertible-debt detection from companyfacts is weak (dimensional facts omitted). Research desk must confirm convertibles from the debt note in Phase 6.
- Phase 3 layout: `data_desk/` = tags (line -> US GAAP/IFRS candidates), xbrl (extraction, restatements = latest filed,
  FY label = year of end date except first week of Jan, LTM = FY + YTD - prior YTD with 7-day tolerance for 52/53-week
  quarters), standardise (derived lines: total debt = current portion + ST borrowings + LTD, leases, net debt, EBITDA,
  FCF, EBIT proxy when no operating-income tag), fx, adr, checks, fmp_statements, builder (only I/O).
  `engine/` = values (traceable Value + calc), model (Historicals/Period), flags, analysis.
- Market-cap hard stop only applies with a point-in-time share count (dei cover page or balance-sheet shares). When
  only a weighted-average count exists (e.g. GRAB 20-F, DASH multi-class) it is amber "approximate".
- Lease balances are tagged annually only: LTM carries the latest FY lease balance forward (noted on the value).
- If EDGAR has a newer annual filing than the XBRL data (TSM FY2025 20-F not yet in companyfacts), amber flag.
- Statement checks cover the last 5 FY + LTM (older years only appear in an expander).
- Grab known differences vs the user's model (agreed Checkpoint 2): D&A 177 vs 101, capex 97 vs 101, debt 2,053 vs
  1,600, cash & investments 6,804 vs 6,861. Revenue and shares match within 0.5%.
- Live sweep (16 tickers incl. JPM, O, TRV, TSM): no crashes, no false hard stops.
- Phase 3 independent review (sub-agent) found: debt double-counted/missed for CVX, MU, O, TRV; leap-day crash;
  CVX cash missing; LTM tag mixing; FMP quarter validation; stale 20-F share counts. All fixed with regression tests
  (tests/test_review_regressions.py, golden total debt for 9 fixtures). Debt order: reported all-in total ->
  balance-sheet parts -> LTD incl. current + short-term borrowings -> IFRS borrowings; finance leases not re-added
  when the debt tag includes them; CVX-style overlapping tags flagged amber.
- Banks/REITs (JPM, O) show "missing key line" for operating income etc.: expected until the Release 3 toolkits.
- Phase 4 engine: engine/dcf.py (conventions switchable: mid/end-year, stub, GAAP vs adjusted margins + SBC,
  sales-to-capital vs explicit capex/D&A, value-driver vs Gordon-on-final-FCF terminal), wacc.py, classify.py,
  forecast.py, scenarios.py, shares.py, sotp.py, valuation.py (orchestrator, pure EngineInputs -> Valuation);
  data_desk/valuation_inputs.py assembles inputs (FRED DGS10, Damodaran ERP/betas/margins/growth/S2C/ratings/tax,
  CRP from FMP revenue geography, consensus from FMP).
- test_grab_engine reproduces the user's model exactly (value per share, every FCF, TV, EV, 25-cell data table).
- Rules chosen (documented in module docstrings): CRP relative to the US CRP (ERP is the US implied premium);
  emerging-market companies without a geography split use the regional CRP; net-cash companies' synthetic rating
  floored at A3/A-; consensus EBIT >3pts from GAAP margin treated as a different basis (only its change used);
  history growth without consensus clipped to [-15%, 30%]; cyclicals use long-run CAGR clipped to [-5%, 10%];
  sales-to-capital on operating invested capital (ex goodwill/acquired intangibles); mature-stable margin target =
  5-year median; terminal ROIC halfway between WACC and current ROIC (capped 40%) if ROIC > WACC, else WACC;
  completed-but-unreported fiscal years are forecast but not discounted.
- FMP publishes consensus mean only (no median): stated on the row.
- Options/RSU counts are rarely in companyfacts: diluted shares fall back to the company's own EPS dilution.
- SOTP needs segment profit: comes from the research desk in Phase 6 (FMP segments blocked on the free plan).
- Phase 4 independent review (sub-agent) fixes: cash flow from the latest balance-sheet date counted (date-based
  timing per year: undiscounted before today, mid-period after); US GAAP operating leases excluded from valuation
  debt (cost already in operating income; IFRS 16 leases included) via `debt_for_valuation`; Gordon TV under
  mid-year discounting dated mid-year N; no tax on losses (carry-forward within the forecast); terminal NOPAT must be
  positive; scenario margins shifted in points (bear -3, bull +2) so loss-makers order correctly; declining bull
  case capped at 0% growth; missing revenue/operating income -> ValuationError; country default spread (CRP/1.52)
  added to cost of debt; amber flag when debt exists but interest expense is untagged; reverse DCF solves growth
  and margin with a grid scan (no monotonicity assumption); 90th-percentile margin flag unconditional (per
  CLAUDE.md); high-growth = 5 explicit years easing halfway to industry growth, then 5 fade years.
- Default terminal growth min(2.5%, risk-free) is a major driver with rf at 5.2%: shown at Checkpoint 3.
- Checkpoint 3 (2026-10-15): user approved. Decisions: industry beta stays the default (easier to explain, editable).
  Tax: effective rate held through the explicit forecast, statutory rate in the terminal value (+2-3% for KO/AAPL).
  User authorised continuing autonomously through the phases; stop at Checkpoint 4 for them to try Release 1.
- Phase 5: engine/comps.py (peer filter + widening, multiples, implied prices, benchmarking), history_multiples.py
  (split-adjusted Tiingo closes x restated diluted shares), verdict.py (50/30/20 blend, +/-15% bands, confidence,
  football field), bridge.py (user model -> tool, 9 ordered steps); core/store.py (SQLite consensus snapshots for
  30/60/90-day revisions: none until history accumulates); data_desk/peers.py, history_data.py;
  desks/modelling.py (ValuationReport with trace registry, assumptions table, sources).
- Peers: FMP + Finnhub candidates kept only if SEC-registered US listings; mega caps (AAPL, KO) need widening
  -> confidence reduced. Forward P/E mostly unavailable on free FMP (consensus blocked for most peers).
- test_grab_judgement: user $5.39 -> tool $1.46; operating margin step -$2.86 is the largest driver.
- Click-to-trace data: every headline number has a Value in report.trace (UI in Phase 7).
- Phase 6: desks/ai.py (structured JSON via output_config.format + jsonschema; Sonnet calls use server-side
  refusal fallback "default"; AI response cache keyed by exact request = determinism; cost ledger in SQLite with
  per-report / per-day caps checked before each call), number_guard.py (+ guarded.py: regenerate once, then drop
  sentences and log), research.py (Haiku, 3 smaller schemas because one schema exceeded the grammar limit; quotes and
  numbers verified against the filing), review.py and md.py (Sonnet), engine/rubric.py (code half of the rubric,
  rating map, one-notch rule), summary.py, pipeline.py (desk status queue, research || peers, saved reports).
- DECISION FOR USER: brief says temperature 0, but claude-haiku-5-5 / claude-sonnet-5-5 reject non-default sampling
  parameters. Determinism comes from caching AI responses by request hash instead (same data -> same output).
- Live Uber run: Buy (Medium), AI cost $0.20 (cap $0.50), ~3.5 minutes; review desk overrode stage to mature growth.
- Filing extraction: Item 1/1A/7 + segment note (10-K), Items 4/3.D/5 (20-F); ASML's integrated report extracts
  only partly (fallback headings).
- Phase 5 independent review fixes: P/E dropped when net income is distorted (company, peers, history years; Uber
  moves from Undervalued to Fairly valued); historical share counts restated for splits after their filing date
  (NVDA FY2022); debt-free peers kept (missing debt = 0 when a balance sheet exists); peer forward EPS only for US$
  reporters; forward EPS = first fiscal year ending after the valuation date; size fallback limited to 0.02x-50x
  (fewer peers accepted, flagged); leverage benchmark skipped when EBITDA <= 0; confidence counts distinct flag codes
  and no longer double-counts consensus / peers; peer market cap = price x SEC cover-page shares.
- Known: KO/AAPL DCFs sit well below other methods (statutory terminal tax, margin fade, 5.2% rf); research-desk
  one-off adjustments lift mature-stable margin targets in full pipeline runs.
- Phase 7 UI: pages/home.py (search + Analyse + recent saved reports), pages/report.py (worker thread + status
  queue progress panel with spinner/tick/cross/dot, elapsed time, running AI cost; verdict card appears as soon as
  the model is ready; edit-assumptions form recalculates the full model; Re-run saves a new dated version),
  ui/report.py (sections 0-22, hover any number for its trace), pages/track_record.py + engine/track.py
  (returns vs SPY and SPDR sector ETF, hit rates at 1/3/6/12 months, moved toward fair value, filters).
  Reports are pickled under data/reports/ (gitignored).
- Phase 8: exports/excel.py (Cover, Inputs, Historicals, Ratios, Forecast, WACC, DCF, SOTP, Comps, Hist multiples,
  Scenarios, Sensitivity, Summary + Calc tab with a full formula DCF per scenario and per sensitivity cell);
  exports/verify.py (pycel + MEDIAN plugin) and scripts/excel_check.py (real Excel via pywin32). Verified: UBER 9,611,
  KO 5,249, GRAB 9,584 formulas, zero errors, Excel fair value = app fair value exactly; GRAB also checked in
  Microsoft Excel. exports/pdf.py (reportlab, 7 pages for UBER).
- Phase 9: README written. Live tests at the end of 2026-10-15: SEC, FRED, Damodaran pass; FMP (429 daily limit) and
  Tiingo (hourly limit) failed only because today's heavy testing used up the free quotas.
- CHECKPOINT 4 reached (2026-10-15): waiting for the user to try Release 1.
- Checkpoint 4 decisions (user, 2026-10-16): response caching replaces temperature 0 (accepted); keep the server-side refusal fallback on Sonnet calls; keep the review desk's stage override. User wants the app as a password-protected personal website with a polished look.
- Deploy brought forward (user, 2026-10-16): Streamlit Community Cloud now, before Release 2; dark clean theme for
  now, full design pass later. Built: `core/db.py` (one interface over SQLite and Postgres; `?` placeholders,
  ON CONFLICT upserts), Store and CostLedger on it, saved reports moved from .pkl files into a `reports` table
  (zlib-compressed pickles; local .pkl files imported once and renamed .pkl.imported), AI response cache stored in
  the database when deployed (determinism survives restarts), `ui/auth.py` password gate (hmac compare, 5 tries
  then 60 s lockout per session; deployed app without APP_PASSWORD stays locked), `.streamlit/config.toml` dark
  theme, `scripts/deploy_prep.py`. Hosted DB: Neon rather than Supabase (Supabase free projects pause after a
  week idle and need a manual restore; Neon wakes automatically).
- Found and fixed: `.gitignore` excluded the whole `exports/` package, so the Excel/PDF code had never been pushed.
- Verified on a real Postgres 18 (portable, in scratch): storage tests on both engines (tests/test_db.py, Postgres
  runs when VT_TEST_PG_URL is set), login flow via AppTest, a full live KO report saved, reloaded and re-run
  (identical fair value and rating, AI $0.000 on the re-run), deploy_prep idempotent.
- KO fair value $36.05 (2026-10-15) vs $45.94 (2026-10-16): the earlier run had no historical-multiples leg
  because the free price quotas were used up; today it is $80.71 and enters the blend. DCF 28.84 -> 30.44, comps
  48.07 -> 48.58.
- 2026-10-23 security fix: the deployed app (no secrets saved yet) let visitors past the gate. Cause: Streamlit
  auto-builds a sidebar menu from a `pages/` folder whenever st.navigation has not been called, and the gate
  stopped the script before st.navigation, so that menu appeared on the locked screen and opened pages directly.
  Fix: pages/ renamed views/; app.py calls st.navigation (hidden until logged in) and stops before nav.run().
  Tests: direct page URLs while locked or logged out (AppTest switch_page), no pages/ folder; checked in Chromium
  against a local server (/, /track_record, /debug, /report all show only the login form).
- 2026-10-26 DEPLOYED and verified: https://aslamanalysis.streamlit.app (public link, APP_PASSWORD gate, Neon
  Postgres). Checked in a headless browser: login on every page URL, saved reports load from Neon, Track Record
  fetches live prices, SEC search works. Live KO report run by the user on the site: all six desks done, Overvalued,
  fair value $46.99 vs $92.70, MD Hold (Medium), AI $0.188, saved to Neon with its track-record row; number guard
  dropped 1 sentence. Remaining: design pass (user's choice of timing), Release 2, Release 3.
- 2026-10-29 Phase 10 done (design pass deferred to the end, user 2026-10-29). Exposure profile in code
  (data_desk/exposure.py): geography, commodities (filing, else SIC default, labelled), rates (verified quote + XBRL
  debt/interest), FX, customers/suppliers/regulators (labelled AI-extracted, names only). News desk (desks/news.py):
  Haiku + web search (basic tool for Haiku), candidates from SEC 8-K/6-K (1-hour fetch) and Finnhub, all rules in
  code: link must be a search result or candidate; date from search page_age (coarse ages read as oldest possible),
  SEC filing date or Finnhub time, else dropped; tier limits 7/14/14/30 days; latest earnings release always kept
  (8-K Item 2.02, 6-K by document name); macro items must name an exposure channel exactly; quote pages and future
  dates dropped; headlines from the source, not the AI; SEC items carry no AI summary (text not read); labels
  Trusted/Established/Unverified by domain; fetched text escaped. News cache 1 hour; "News as of" is the search
  time. Runs in parallel with modelling/review/MD, joined with a 180 s limit before save; never breaks the report.
  AI client: pause_turn resumed, answer = text after the last search result, per-request pricing, spend reserved
  under a lock so parallel desks can't overshoot the cap. Independent review: 13 findings, all fixed with tests.
  Live: CVX 10 items (4 macro on US/oil/rates channels), GRAB 9 items (Thailand/Philippines/Vietnam macro, 6-K
  earnings release); about $0.11 per news run. Full CVX report with news: 115 s, AI $0.232.
- 2026-10-29 Phase 11 done. Impact analyst (desks/impact.py, Sonnet, number-guarded): 7-step analysis per item;
  the AI proposes driver + size, code decides: per-item bounds (growth 10pt, margin 5pt, s2c 1.0x, WACC 1.5pt,
  terminal growth 0.5pt, scenario probability 25pt), combined change per driver held to the same bound, Unverified
  items never sized themselves (counted once through a Trusted/Established item on the same driver and sign),
  sensitivity quotes must be verbatim from the filing. Code reprices (engine/news_impact.py: copy of the engine
  inputs, value_company, same blend; comps/history held; SOTP scaled by the DCF change; refuses changes that break
  the DCF or add a hard stop; shifts start at the first forecast year; builds on user overrides). Priced in: abnormal
  return since the news vs SPY and the sector ETF (same mapping as the track record), one common window, 1% noise
  floor. News-adjusted fair value shown next to the base (base stays news-free). MD: news feeds the catalysts
  criterion; separate "What the news means" call after the rating. Refresh news button: own cost run id (per-report
  cap; daily cap still applies), works on a copy, keeps saved news if the search fails, notes the rating predates
  the refresh. Guard: news headlines from Trusted/Established sources are quotable; summaries are not. Independent
  review: 10 bugs + nits, all fixed with tests. Live CVX refresh: 9 items, 2 quantified, base $151.51 ->
  news-adjusted $150.86, Overvalued, Hold unchanged; refresh about $0.19-0.22.
- 2026-10-29 Phase 12 done (code only, no AI). Ownership (data_desk/ownership.py): Form 4 (180 days, latest 60
  filings; window shortened and stated when capped), open-market P/S counted, exercises/grants/withholding listed
  only, 10b5-1 flag, 4/A restatements counted once; Schedule 13D/13G XML (3 years, latest 40, one row per filer CIK
  and share class; pre-2024 text filings counted and noted); filings about other issuers (the company as an owner,
  e.g. Berkshire's stakes) excluded by issuer CIK; FINRA short interest (free API, share-class symbols as BRKB),
  % of US-listed shares (ordinary / ADR ratio); FMP 13F for the last quarter past its 45-day deadline (restricted
  on the current plan: noted). Each section isolated; runs in parallel with research and never stops the report.
  Forensic (engine/forensic.py): Beneish 8-variable M (-1.78) and Altman Z (SIC 2000-3999, market equity) / Z''
  (others, book equity), on reporting-currency statements (market cap converted at the period-end FRED rate),
  financials skipped, every input traced, accumulated-deficit caveat. Numbers passed to the AI desks as numbers.
  Independent review: 11 bugs + nits, fixed. Live: CVX 26 sells / 0 buys, State Street 7.5%; GRAB CEO buys
  $30.7m, Z'' -1.47 explained by the -17,470m accumulated deficit with net cash.
- 2026-10-29 Phase 13 done. Compare page (views/compare.py): two saved reports (latest per ticker) side by side:
  price, fair value, verdict, MD rating, news-adjusted fair value, stage/toolkit/WACC, key metrics (LTM, latest
  FY fallback labelled), multiples vs peer medians, both football fields. Saved reports only: no API cost.
- 2026-10-30 Phases 14-15 done (financial toolkits, engine/financials.py, no DCF). Routing by SIC: banks 6020-6039,
  6111, 6712; insurers 6300-6399 except 6324 (managed care stays corporate: valued on operating profit); REITs 6798.
  Cost of equity = rf + levered industry beta x ERP + CRP. Long-run g = max(0, min(sustainable, rf - 0.5pp, 3%));
  REITs min(2%, rf - 0.5pp). Retention = 1 - (dividends + buybacks) / net income, 3-year average (book grows only
  by what is neither paid out nor bought back). Methods and weights: banks/insurers justified P/TBV (P/B)
  (R-g)/(CoE-g) 30, residual income (return fades to normalised over 3 years, excess return to 50% by year 10)
  30, DDM two-stage 10, peer P/TBV 15, peer P/E 15; REITs NAV (EBITDAre / median peer cap rate - net debt) 40,
  peer P/FFO 30, DDM 30. Peers restricted to the same toolkit; medians need 3+ peers. Reported KPIs (CET1, SLR,
  NIM, ROTCE, TBVPS, combined/loss/expense ratios, FFO/AFFO per share) read deterministically from the 10-K text
  (primary + split _dN documents + EX-13) with a verbatim quote and range checks; whole-number parsing, amounts
  ("billion") and column years rejected. Golden fixtures (tests/fixtures/fin): JPM CET1 14.6%, ROTCE 20%, NIM
  2.50% (managed basis), TBVPS 107.56; TRV combined ratio 89.9%; O FFO 4.25 / AFFO 4.28, independently checked
  against the filings by a separate agent. Excel workbook (exports/excel_fin.py) rebuilds every method in
  formulas and ties to the app (checks ~0); PDF and edit form (only changed values become overrides). Live:
  JPM 302.96 vs 343.58 (Fairly valued), TRV 376.60 vs 398.27 (Fairly valued), O 57.11 vs 57.20 (Fairly valued).
- 2026-10-30 Smoke test (28 tickers) fixes: cover-page share counts rejected when stale (NKE tagged 2015) or
  outside 0.5-2x the weighted count (BABA FY2026 20-F tagged 1.86bn vs 18.6bn); EDGAR now carries foreign
  countries in `country` (CRP for BABA/TSM/SHOP was zero); foreign-filer test scans all recent forms (TSM's last
  200 are 6-Ks); catch-all SICs (7389 etc.) use the market average with an industry-proxy flag; FX-on-cash and
  change-in-cash tags including disposal groups (AMZN, TSLA, UNH cash ties); EBIT proxy from net non-operating
  interest (NKE); market-cap gap vs a secondary provider (Finnhub) is amber, the hard stop stays FMP-only; HTTP 429
  cool-down (10 minutes) so a quota-exhausted source fails fast; profitable early-stage companies keep their margin
  rather than ramping down to a lower industry aggregate (SHOP); loss-making decliners revert toward their
  10-year average margin instead of holding a perpetual loss (INTC).
- 2026-10-31 Caveat fixes (user asked for these before the design pass):
  - Peers without FMP: SEC frames (one XBRL line for every filer) give revenue for all US-listed companies; the
    nearest 60 by revenue (0.25x-4x) are checked for the same 2-digit SIC and up to 8 join the FMP/Finnhub
    candidates (AMZN +CVS, JD; MSFT +META, GOOGL, BABA). Peer multiples above a "not meaningful" ceiling (P/E,
    EV/EBITDA, EV/FCF 100x; EV/Sales 50x) are excluded and listed, in the app and the Excel formulas (CRWD's
    5,700x P/E had stretched MSFT's comps range to $9,000+).
  - TSM: its 2025 20-F uses the IFRS 2025 taxonomy, which SEC companyfacts has not ingested (only dei facts).
    data_desk/instance.py reads the filing's own XBRL instance and merges it (facts already present are not added
    twice); figures carry "SEC EDGAR filing (XBRL instance)" and the accession. IFRS bonds tags added (TSM debt
    NT$75bn -> NT$1,068bn, 0.4% from FMP). FMP's quarterly share counts for ADR issuers are in ADSs and are now
    multiplied by the ADR ratio (TSM LTM market cap was 5x too low).
  - BABA: not in Damodaran's company list; mapped by hand to Retail (General), Damodaran's industry for AMZN,
    EBAY, MELI and CPNG (info flag, not the proxy flag). Balance-sheet share counts are dated at period end, so a
    7-month-old count gives an amber approximate market-cap check rather than a hard stop (BABA 6.6% vs FMP).
    EDGAR vs FMP share cross-check compares ordinary shares (FMP counts ADSs).
  - JPM NIM: JPM publishes only the managed-basis (FTE) yield, 2.50%; the reported margin is derived as
    2.50% x reported / managed NII (95,443 / 95,868) = 2.49%. CET1 14.6% confirmed as the binding (Standardized)
    ratio; user had the figures and the "fairly valued, leaning expensive" read checked independently.
- 2026-10-31 Mature-company valuations (KO was $46.99 vs $92.70, -49%; analyst targets $86-104). Causes found by
  changing one assumption at a time: long-term investments valued in the equity bridge were also in invested
  capital (KO's ~$20bn of bottler stakes: ROIC 17.4% instead of 24.8%, sales-to-capital 1.04 instead of 1.83) -> now
  excluded unless operating income is an EBIT proxy; EV/Sales left out of the comps value when the company's
  operating margin is outside 2/3x-1.5x the peer median (KO 29.5% vs PEP/KDP/MNST-type peers); mature/declining
  companies without consensus use the 3-year revenue CAGR rather than the latest year; XBRL goodwill and intangible
  impairments added back to the 5-year margin history (max with the research desk's one-offs; restructuring not
  added back, it recurs). KO no-AI run: $58.45 (-37.9%), DCF $47.01, comps $62.67, history $80.71; PG $159.53
  (-1.3%). The rest of the gap is the discount rate: 7.0% WACC (rf 4.98% FRED, beta 0.62, ERP 3.7% Damodaran);
  ~6% is needed to reach the price. The saved Oct 26 KO report predates long-term investments in the bridge.
  Open: AAPL -48.6% (DCF $101; WACC 9.8% from a 1.34 regression beta; no consensus while FMP is rate-limited);
  FMP consensus shows KO revenue flat FY2026-FY2027 (49,826 -> 49,846), not yet explained.
- 2026-10-31 Gap to analyst targets (user: "clearly something is wrong if banks are valuing it higher"). Rebuilding
  KO's DCF with sell-side assumptions one at a time (today's data + saved consensus): ours $42.89 -> consensus all
  years $45.84 -> comparable margin ~31% $55.01 -> own tax rate in the terminal value $58.16 -> ROIC held $61.53 ->
  3% terminal growth $67.09 -> WACC 6.5% $76.88 -> 6.0% $89.72 (price $94.08). Built: consensus revenue growth for
  every forecast year with 3+ analysts (was years 1-2; KO's flat FY2027 from the CCBA deconsolidation had set the
  whole path), last explicit year converging on terminal growth; research desk lists one-offs for every year the
  MD&A discusses and reads the annual reports from 2 and 4 years earlier (MD&A only) for the older years, newer
  reports winning for overlapping years; a year's net one-offs above half its operating income are dropped as a
  likely double count. KO check: adjustments FY2021-25 846 / 1,212 / 1,951 / 3,995 / 1,189 (FY2021 and FY2023
  equal KO's XBRL OtherCostAndExpenseOperating; clean FY2025 margin 31.2% = KO's reported comparable margin);
  margin target 25.5% -> 29.0%; DCF $50.47 (weighted $52.59). Reverse DCF adds the implied discount rate (KO 4.9%
  vs our 7.0%) and a DCF at three common sell-side conventions, same discount rate (own tax rate in perpetuity,
  today's ROIC held, 3% terminal growth): KO $62.79, implying 5.6%. Shown in the report and the PDF.
- 2026-10-31 tests/test_pipeline_offline.py: a whole report offline (KO EDGAR fixture, recorded engine inputs and
  Damodaran files, stub market data, a fake AI returning schema-valid answers with research segments and one-offs);
  every desk runs, segments reach the SOTP, the report saves and reloads. Reintroducing the MSFT bug fails it with
  the original TypeError. What if tab (ui/report.py what_if): sliders for WACC, terminal growth, target margin,
  terminal ROIC and a growth shift reprice the DCF via engine.news_impact.reprice (~10 ms; comps and history held);
  presets: base case, sell-side conventions, market's discount rate (DCF = price). MSFT at the market's rate: DCF
  $520.18 vs price $521.91; CVX $229.01 fair value vs $231.45.

### 2026-10-31: History tab, Compare, search box, landing chart
- Report page **History** tab: fair value vs price across every dated report of the company (rating labels), and a
  timeline whose "what changed" note is written by code from the saved versions (method values, WACC, year-1 growth,
  target margin, stage, price).
- Anthropic API failures (e.g. out of credit) become `AIError`, so a report still completes its valuation without
  the AI desks (JPM run of 2026-10-31 failed outright before). Tested offline.
- Compare: each company card carries the report's value strip; key metrics gain a "Stronger" column.
- Search box themed via `style_overrides` (it renders outside the page CSS).
- Landing hero draws the newest report's last year of daily closes (read from cache, never the network) against its
  fair value and DCF bear-to-bull band, with the source and dates; decorative line only as a fallback.
- Phone width (390px): no horizontal page overflow; tabs scroll sideways.

### 2026-10-31: explaining the valuation, reading guides
- `engine/insights.py` (pure, `tests/test_insights.py`): `price_walk` (one assumption at a time from our DCF to the
  price; steps under 0.5% applied but not drawn; the changes sum to the gap), `value_split` (NOPAT / WACC against
  growth, ours and the market's), `monte_carlo` (2,000 runs, seed 7, sd = bear-bull step / 2 / 1.2816, terminal
  growth kept 1 point under WACC and under the risk-free cap), `peer_regressions` (OLS, at least 5 peers).
- `ui/insights.py`: waterfall, stacked no-growth/growth bars, histogram with the 10th-90th band, scatter with the
  fitted line. Shown in the DCF, comps, reverse DCF and scenarios sections; the PDF carries the same figures.
- KO: DCF $42.22 -> margin +1.31 -> tax +3.32 -> ROIC +2.36 -> 3% g +3.36 -> WACC 5.7% (+41.51) = $94.08; growth is
  22% of our EV and 64% of the market's; Monte Carlo 10th-90th $35.01-50.59, 0% above the price; EV/Sales vs
  margin R2 0.88 (extrapolated). UBER: 42% of versions above the price. GRAB: growth subtracts value in our DCF
  (said in words). Banks, insurers and REITs: not shown (no DCF).
- Reading guides (`ui.theme.guide`): "Start here" under the header (with the blend weights), "In this tab" on every
  tab, and "How to read this" / "Why this number" on the stage, forecast, WACC (with its arithmetic), DCF, comps,
  reverse DCF, scenarios, football field and flags.
- Tiingo refusing a refresh (hourly limit) now falls back to a series cached within 3 days; KO's 20:33 run had lost
  its own-history multiples to this.
- **Talking points** page (`views/interview.py`, `ui/talking.py`): the 30-second version, a worked example built from
  any saved corporate report (headline figures, the walk, value split, Monte Carlo, regression; the sentence about
  the walk is worded from the signs and sizes of its steps), the design decisions and the questions to expect.
  Checked on KO, MSFT, TSM, UBER, GRAB and CVX; JPM shows why there is no walk. Tested offline.

### 2026-11-01: hero fix, correlated Monte Carlo
- Landing hero (MSFT on the deployed site): the line ran through the title and text, the DCF band read as a block
  and the end dot was clipped. Chart narrowed with a longer fade, band drawn faint with hairline edges, dot inset.
- Deploys into a running server: app.py drops the project's modules when any source file has changed (the
  ImportError after the insights push came from a stale ui.theme kept in memory).
- Monte Carlo: growth and margin shifts drawn with the company's measured correlation (revenue growth vs change in
  operating margin, >= 6 years, capped at +/-0.8); 0 gives exactly the old independent draws. Measured: CVX 0.95
  (used 0.8), TSM 0.89 (0.8), MSFT 0.43, UBER 0.13, KO -0.28, GRAB not measured (5 years). Effect on the 10th-90th
  range: CVX $81-175 vs $81-166 independent; MSFT $273-383 vs $278-374; KO $35.69-49.82 vs $35.01-50.59.

### 2026-11-01: Excel stored values, segments from XBRL, provider flag
- Excel: every formula's result stored in the file (pycel), so sheets show numbers in Protected View and previews;
  formulas stay live. Comps and history multiples bridges leave out long-term investments, as the app does.
- SOTP: segment revenue and operating income read from the 10-K XBRL segment note (business-segment axis, with
  ConsolidationItemsAxis = OperatingSegmentsMember; aggregates and eliminations left out), research-desk names and
  comparables matched by operating income then words. Segments with operating profit valued on comparables' median
  EV/EBIT (EV/Sales otherwise); unallocated corporate costs capitalised and deducted. The SOTP sheet shows metric x
  multiple as live formulas. MSFT: SOTP $390.52 (was $235.42 on EV/Sales), fair value $343.56 -> $421.11 on re-model.
  KO: segments read (five, with revenue now), not applied as Latin America has no usable US comparable.
- CVX and GRAB re-run on the current engine; the CVX run hit FMP's rate limit, so reports now carry an amber
  "provider unavailable" flag when a data provider refused requests during the run.
- Excel Analysis tab: walk to the price (steps from the app, changes as formulas), no-growth split (NOPAT / WACC
  from the DCF tab's cells), Monte Carlo percentiles (correlated and independent), peer regressions with live SLOPE /
  INTERCEPT / RSQ and implied price. Check rows 0.00 for KO, MSFT, UBER, CVX, GRAB, TSM; KO recalculated in Excel 16
  (R2 0.8788 and 0.5943, implied $52.82 and $37.10, as the app). JPM (bank toolkit) has no DCF, so no tab.
- Dividend cross-check (engine.insights.dividend_check; Valuation tab after the no-growth split, PDF, Excel
  Analysis section 5 with live formulas on the DCF tab's NOPAT row): KO $36.10 (price $94.08 implies 5.9% dividend
  growth for ever), CVX $133.92 (3.1%); MSFT, TSM below the 1% yield cut-off; UBER, GRAB pay none. Excel check rows
  0.00.
- Foreign peers: a home-market market cap (e.g. KOF in MXN from Finnhub) is converted at FRED's latest daily rate
  instead of the peer being dropped (data_desk.peers.usd_market_cap). KOF: US$24.8bn, EV/EBIT 11.3x. This let KO's
  SOTP apply on re-model: five filed segments + corporate costs = $51.94 a share (DCF $43.47); fair value on
  re-model $65.32 (the saved report shows the old run until KO is re-run).
- Piotroski F-score (engine.forensic.piotroski): nine pass/fail tests per fiscal year; a test without inputs is not
  scored (fewer than 7 scored: no score); net income attributable as the fallback. Shown with the failed tests;
  saved reports get it computed from their stored statements. FY latest: KO 7, MSFT 6, UBER 6, CVX 5, GRAB 5, TSM 9;
  JPM not meaningful (bank).
- Peers that are successor issuers (XOM: ExxonMobil Holdings Corp, new CIK after the July 2026 reorganisation) were
  dropped with "no XBRL financials"; peer_metrics now reads the predecessor's history as the main company does.
  CVX's peers: XOM, OXY, MPC, PSX (was OXY, MPC, PSX). Tried adding IFRS revenue frames for 20-F majors (BP,
  SHEL, TTE): SEC's frames API does not serve ifrs-full, so those still come only from the market-data providers.
- Return on new capital (engine.insights.return_on_new_capital, flags in engine.valuation.reinvestment_flags, line in
  the no-growth view): KO 32.8%, MSFT 44.1%, UBER 27.4%, GRAB 16.0% (all above WACC); TSM 9.2% < 12.4% WACC (amber:
  the margin fades 58% -> 39% under mean reversion while TSM earns 47% today); CVX profit falls while reinvesting
  (info). Source: Damodaran's consistency checks (reinvestment rate = g / ROC).
- Considered slowing margin mean reversion for persistently high-margin companies (TSM). Not done: Mauboussin
  (2007, ~1,000 companies 1997-2006) finds 41% of the top ROIC quintile still there after nine years (20% by
  chance) but no reliable predictor of which; the fade stays, the reinvestment flag shows its cost, and the
  Talking points page answers the question.
- Industry dataset by revenue geography: Damodaran files TSM under Emerging Markets, so its beta (1.98) and the
  margin it fades to (20.4%, 546 mostly smaller emerging-market firms) came from the emerging dataset. An
  emerging-market listing with >= 50% of revenue from developed markets (FMP geography) now uses the global dataset
  (TSM 90%: beta 1.87, margin 27.0%). Re-model: WACC 12.38% -> 11.99%, DCF $119.99 -> $123.93. Unknown geography
  keeps Damodaran's classification (GRAB). Note: offline re-models differ from saved reports also because FMP is
  rate-limited today (no consensus) and the review desk's stage override is not replayed.
- Cache fallback: when a refresh fails for a passing reason (HTTP 429, 5xx, no connection) the last good copy is
  served, with its own fetch date, if recent enough (30 days; consensus 7; prices, news and AI never). The run's
  notes list each fallback. Live: FMP was refusing CVX, and its 29 Oct consensus came back instead of nothing.
- Tornado chart (engine.insights.tornado, Valuation tab before the Monte Carlo): one input at a time to its bear and
  bull setting, sorted by swing. KO: growth $37.25-$47.75, WACC $38.74-$46.40, margin $37.64-$45.27.
- PDF: tornado table in section 14 (input, bear/bull setting, values, swing).
- Excel Analysis tab: section 6, the tornado (bear, bull, swing as a formula).
- Monte Carlo pooled correlation: under six years of its own history, the growth-margin correlation is pooled
  across the company and its peer pool (each firm demeaned, at least 3 firms x 4 years and 15 firm-years). Peers
  now carry growth_margin_pairs. GRAB: -0.18 over 43 company-years (GRAB, LYFT, MMYT, PDD, RYDE, UBER). Saved
  reports pick it up on their next run.
- 1 Nov re-runs (KO, MSFT, TSM, CVX, GRAB; AI $2.14): docs refreshed. TSM now earns 15.3% on new capital vs 12.0% WACC (margin fade 58% -> 42.5%), so the amber flag no longer fires; README and Talking points no longer cite it as flagged.
- Economic profit view (engine.insights.economic_profit; Valuation tab after the value split; PDF line): EV =
  capital today + PV of yearly economic profit + terminal value above end capital, exact (check 0 on six reports).
  Capital is charged at WACC for calendar time in use (opening capital to year end, new capital from mid-year), so
  a part year 1 and mid-year discounting don't distort it. Capital from the US$ balance sheet at the DCF base year
  (TSM was in TWD before the fix). KO: 49.3bn + 34.7bn + 107.7bn = 191.7bn.
- Excel Analysis tab section 7: economic profit as live formulas on the DCF tab's NOPAT, reinvestment and timing rows; check = sum - DCF EV is 0 on KO, MSFT, TSM, CVX, GRAB, UBER.
- Compare: cross-checks add the share of EV from value created above capital (GRAB 32.4%, CVX 19.7%).
- Tried and dropped: Mauboussin's market-implied forecast period. Our forecasts converge to terminal growth (2.5%) by the final year, so extending them mostly measures terminal ROIC vs WACC; most results were 'beyond 60 years' and CVX's own DCF could not be matched. Choosing a different growth to extend would be an unsourced assumption.
- Talking points worked example: 'Which assumption matters most' (top two tornado inputs) and 'Capital or value created?' (EP share of EV), from the same functions as the report.
- SOTP: a research segment whose quote fails verification keeps only its name and comparables (segments_unverified), used only when its name matches an XBRL segment. UBER now gets all three segments with comparables; the SOTP still correctly does not apply (Freight 9.8% of revenue, Mobility/Delivery growth gap 7 pts, no segment margins in XBRL).
- Research quote check ignores the '|' the text extractor puts between table cells: quoted table rows were failing verification. Dropped items across KO, MSFT, TSM, CVX, GRAB, UBER: 42 -> 8 (GRAB 19 -> 2; UBER segments 0 -> 2 verified). Recovered one-off items feed margin normalisation, so the six were re-run.
- Research number check: a negative figure (segment loss) passes only when the filing shows it as negative, '(110)' or '-110'. Before, every negative failed (unsigned source tokens): GRAB Financial Services (-110) and UBER Freight (-33) were dropped.
- Excel Cover: a 'Tabs' guide (one line per tab present); Analysis tab description lists all seven sections.
- Terminal value check (DCF section): implied exit EV/EBIT vs peers' median and the company's own today. KO 12.1x vs 17.6x / 27.1x; MSFT 9.6x vs 20.9x / 23.8x.
- Session end 1 Nov: re-runs of GRAB, UBER, TSM saved with the research quote fixes; the batch stopped before MSFT, KO, CVX (re-run those next session). AI spend today US$3.85 of $5.
