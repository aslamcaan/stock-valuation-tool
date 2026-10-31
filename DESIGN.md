# Design

Visual system for the Stock Valuation Tool. Direction chosen by the owner: a **black and orange research terminal**,
alive with motion, with cream text instead of white. Mode: Operate (the visitor reads a valuation and checks its
working), so motion explains state (a desk working, a figure arriving) rather than decorating.
Tokens and components live in `ui/theme.py`; the analysis screen in `ui/run_panel.py`; the PDF has its own print
palette in `exports/pdf.py`.

## Principles

- The call first: every report opens on one header with the ticker, the MD's rating (a ring filled to the weighted
  rubric score), price, fair value, upside and verdict, the model's value range against the price, and the key flags.
  "Why <rating>" and the scored rubric sit directly under it. The working is in tabs below.
- Ratings and reasons over returns: the Track Record shows each call's rating, verdict and the MD's reasons; price
  moves since a call are opt-in and small.
- Colour carries meaning: orange is the model's own figure (fair value, intrinsic methods), focus and the primary
  action; green/red are verdicts and gains/losses; yellow is a warning. Everything else is warm greyscale.
- Never pure white: text is cream (#ede4d3), labels sand.
- Numbers are the hero: IBM Plex Mono with tabular numerals; headings Archivo (expanded); prose IBM Plex Sans.

## Tokens

| Token | Value | Use |
|---|---|---|
| bg | #0a0908 | page (with a faint top glow and graph-paper grid) |
| surface / surface-2 | #13110e / #1b1814 | cards, hover |
| border / border-2 | #2b2520 / #3d342c | hairlines, control edges |
| text / muted / faint | #ede4d3 / #a39a8a / #857b6e | body, labels, captions |
| accent / accent-2 | #ff7a1a / #ffa45c | model figures, focus, primary buttons, links |
| green / red / amber | #6fcf86 / #f2604f / #e9b949 | verdicts, returns, warnings |

Radii: 9px buttons, 12–20px cards, pills fully rounded. Easing: ease-out expo `cubic-bezier(.16,1,.3,1)`.

## Motion

- Signature: the orange scan. The landing hero line draws itself; the analysis screen sweeps a beam across a signal,
  then across the company's real revenue bars once the data desk lands.
- Arrivals: page blocks and tab panels rise in once (blur 3px → 0, 12px → 0). The report header's figures count up
  (CSS `@property` counters), the rating ring fills, the value band grows and the marks drop in.
- Hover: cards lift 3px with an orange edge; buttons glow and press to 97%.
- Analysis screen: re-rendered every 0.4s, so loops take a wall-clock negative delay (`--p9`, `--p14`… on `.vt-run`)
  and one-off animations a delay from when their state began. Nothing visibly restarts.
- `prefers-reduced-motion` turns every animation into its end state.

## Components

- Top navigation (`st.navigation(position="top")`): orange underline slides in on hover, full on the current page.
- `.vt-head` report header; `.vt-rating` ring; `.vt-kpis` figure row (`.two` for 2×2); `.vt-range` value strip whose
  labels flip inward near the edges; `.vt-chip` flag pills, always with a text level.
- `.vt-why` reasons + rubric panels; `.vt-thesis`, `.vt-duel` (bull vs bear, the MD's side marked), `.vt-checks`,
  `.vt-timeline` for the investment view.
- `.vt-run` analysis screen with `.vt-node` desk cards (waiting, running, done, failed, skipped).
- `.vt-hero` + `.vt-tape` (latest calls, pauses on hover) on the landing page; `[class*=st-key-card_]` lifting cards.
- `.vt-dist` rating distribution, `.vt-call` call card and `.vt-mini` price-vs-fair-value strip on the Track Record.
- `.vt-steps`, `.vt-rules` on How it works (rubric weights and cut points read from `engine.rubric`).
- Charts: `plotly_layout()`; football field bars orange (intrinsic), sand (multiples), faint (market references).

## PDF

A sell-side note on white: warm-black masthead with the orange mark, date and report id on page 1; a rating box;
ruled section heads; running header and page-numbered footer; right-aligned numeric columns; fair value and intrinsic
methods in a darkened orange (#d9600b) that prints legibly.
