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
- [ ] **CHECKPOINT 1:** .env instructions → user adds keys → test connections → report unavailable FMP endpoints + alternatives

### Phase 2 — golden fixtures
- [ ] Extract tests/fixtures/grab_model.xlsx → tests/fixtures/grab_expected.json (historicals, assumptions, value per share, cell refs)
- [ ] tests/fixtures/uber_expected.json from the brief
- [ ] Commit + push
- [ ] **CHECKPOINT 2:** show extracted Grab table, wait for confirmation

### Phase 3 — historicals and financial analysis
- [ ] Historicals 5–10 years + LTM, US GAAP + IFRS tag mapping with fallbacks, tag logging
- [ ] Value objects {value, currency, unit, period, source, tag, fetched_at}; unit normalisation
- [ ] FX (FRED; period-average for IS/CF, period-end for BS), ADR ratios, currency-mismatch flag
- [ ] Non-December fiscal years; restated figures; >120-day filing flag
- [ ] Data checks: hard stops (BS balance >0.5%, market cap >3% vs FMP); red flags (sums, cash tie, 1%); EDGAR vs FMP amber (>2%)
- [ ] Ratios and full financial analysis (Section 6 item 4, no Beneish/Altman)
- [ ] Pass `test_grab_data` and Uber test
- [ ] Commit + push

### Phase 4 — engine
- [ ] Sector toolkit classification (SIC) and lifecycle stage; cycle percentile measurement
- [ ] Consensus blending (history | consensus | industry | chosen, source, confidence)
- [ ] Forecast by stage
- [ ] WACC (DGS10, Damodaran ERP, relevered industry beta, revenue-weighted CRP, after-tax Kd, market weights)
- [ ] DCF (SBC as cash cost, mid-year, stub, Gordon TV, g/ROIC reinvestment, equity bridge, treasury-method diluted shares)
- [ ] SOTP, scenarios, sensitivity grids, reverse DCF
- [ ] Pass `test_grab_engine`, KO and cyclical tests
- [ ] Commit + push
- [ ] **CHECKPOINT 3:** valuation summary for GRAB, KO, AAPL

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
  news, insider-trading and institutional-ownership endpoints restricted. Awaiting user decision: upgrade FMP or use free alternatives.
  SEC name/email still placeholders in .env.
