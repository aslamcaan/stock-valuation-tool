# Product

<!-- impeccable:product-schema 1 -->

<!-- Written 2026-10-31 from PROMPT.md, CLAUDE.md and the owner's answers in session (visual direction, scope,
debug page). The owner was away and had asked for autonomous work, so no init interview was held: facts marked
(inferred) were not confirmed by the owner. -->

## Platform

web

## Users

- The owner: builds and uses the tool to research and value US-listed stocks, and shows it in finance job
  interviews as a portfolio piece (confirmed).
- Interviewers and reviewers shown the deployed site: they judge rigour, sourcing and judgement in minutes, often on
  a shared screen (inferred from the portfolio purpose).

## Product Purpose

An equity research and valuation tool. Pick a company; six desks (data, research, modelling, news, review, MD) build
a sell-side style report: verified historicals, analysis, a DCF or sector toolkit (banks, insurers, REITs), comps,
scenarios, a football field, news impact, ownership, a rating, and Excel/PDF exports. Success: a report a finance
professional would trust because every number traces to a dated source.

## Positioning

All arithmetic is code, never AI; every figure carries its source, filing, tag and fetch time on hover; hard stops
refuse to value when the data breaks; AI text is number-checked against computed results. It shows its working the
way an analyst's model does, including what is missing.

## Operating Context

Streamlit app, deployed on Streamlit Community Cloud behind a password, with Neon Postgres. Reports take minutes to
run (live progress panel) and open instantly once saved. Data: SEC EDGAR, FMP (free plan, daily quota), Finnhub,
Tiingo, FRED, Damodaran. Exports: Excel model with live formulas, PDF report.

## Capabilities and Constraints

- Pages: Search (landing), Report, Compare, Track Record, Debug (local only; hidden when deployed, owner's choice).
- Streamlit limits layout control: custom HTML/CSS through markdown, Plotly charts, native widgets.
- UK English in UI and report. Every number shown must trace to a source and date; missing data is stated.
- Free data plans: some sections can be empty (no peers, no analyst estimates) and must say why.

## Brand Commitments

- Name: "Stock Valuation Tool". Visual direction chosen by the owner: refined dark research terminal: number-first,
  tight type, muted accents, green/red reserved for verdicts.

## Evidence on Hand

Real saved reports in the database (MSFT, JPM, KO, GRAB, CVX, UBER). No testimonials, users or performance claims
exist; none may be invented. Track Record shows only real logged calls.

## Product Principles

1. Trust over flourish: provenance and caveats are visible, never hidden to look cleaner.
2. The verdict first, the working one click away.
3. Numbers are the hero: aligned, tabular, consistently formatted.
4. Say what is missing rather than leaving a blank.

## Accessibility & Inclusion

No specific requirement given (inferred baseline: WCAG 2.2 AA contrast, keyboard use, colour never the only signal).
