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
