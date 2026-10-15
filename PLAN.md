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
- [ ] Comps (peer filter SIC + 0.25–4x mcap, min 5), historical multiples, estimate revisions
- [ ] Industry benchmarking percentiles
- [ ] Verdict rules + confidence; flags; football field; assumptions table; provenance / click-to-trace
- [ ] Pass `test_grab_judgement`, ASML, AAPL tests
- [ ] Commit + push

### Phase 6 — AI desks
- [ ] Research desk (Haiku), review desk, MD (Sonnet); temperature 0; JSON schemas
- [ ] Number guard; determinism; cost logging and caps
- [ ] Pass determinism and number-guard tests
- [ ] Commit + push

### Phase 7 — UI
- [ ] Landing page, progress panel (threads + queue), full report, editable assumptions with live recalculation
- [ ] Track Record page with auto-logging (SQLite)
- [ ] Commit + push

### Phase 8 — exports
- [ ] Excel export (banking conventions, real formulas); verify Grab file calculates, matches app
- [ ] PDF report
- [ ] Commit + push

### Phase 9 — README
- [ ] README (architecture diagram, setup, tests, limitations); push
- [ ] **CHECKPOINT 4:** Release 1 summary + run command; wait for user

## RELEASE 2: news, ownership, comparison
- [ ] Phase 10 — exposure profile, news desk (four tiers, freshness, source labels)
- [ ] Phase 11 — impact analyst, priced-in, news-adjusted fair value, MD news summary, Refresh news, rubric feed
- [ ] Phase 12 — ownership, Form 4, short interest, Beneish M, Altman Z
- [ ] Phase 13 — Compare page
- [ ] **CHECKPOINT 5:** news demo on CVX and GRAB

## RELEASE 3: financial-sector toolkits
- [ ] Phase 14 — bank toolkit; extract JPM expected values
- [ ] **CHECKPOINT 6:** JPM fixture confirmation
- [ ] Phase 15 — insurance and REIT toolkits; pass JPM, O, TRV tests

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
