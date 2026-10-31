# Design

Visual system for the Stock Valuation Tool. Direction chosen by the owner: a **refined dark research terminal**.
Mode: Operate (the visitor reads a valuation and checks its working), so ambition shows as precision and restraint.
Tokens and components live in `ui/theme.py`; the PDF has its own light print palette in `exports/pdf.py`.

## Principles

- The call first: every report opens on one header block with price, fair value, upside, verdict and rating, the
  model's value range against the price, and the key flags. The working sits in tabs below.
- Numbers are the hero: figures use IBM Plex Mono with tabular numerals and right alignment; prose uses IBM Plex Sans.
- Colour carries meaning only: blue is the model's own figure (fair value, intrinsic methods), green/red are verdicts
  and gains/losses, amber is a warning. Everything else is greyscale.
- Expected gaps (a desk that did not run, data the free plan lacks) are quiet notes, not alarm boxes.

## Tokens

| Token | Value | Use |
|---|---|---|
| bg | #0b0f14 | page |
| surface / surface-2 | #11161d / #171e27 | cards, hover rows |
| border | #232b35 | hairlines, card edges |
| text / muted / faint | #e6edf3 / #9aa4af / #6b7682 | body, labels, captions |
| blue | #4c8dff | fair value, intrinsic methods, focus ring, primary button |
| green / red / amber | #3fb950 / #f85149 / #d29922 | verdicts, returns, flags |

Radii: 8px buttons, 10–14px cards, pills fully rounded. Motion: the report header rises in once (0.5s, ease-out
expo); nothing else animates, and reduced motion turns it off.

## Components

- `.vt-head`: report header card; `.vt-kpis` five-column figure row (`.two` for a 2×2 grid in half-width cards).
- `.vt-range`: value-range strip with price (white) and fair value (blue) marks; labels sit on the outer side.
- `.vt-chip` flag pills (hard stop/red, amber, info), always with a text level, never colour alone.
- `.vt-table`: dense ruled tables; prose tables (`.text`) left-align.
- `.vt-note`: quiet notice for expected gaps.
- Charts: `plotly_layout()` for transparent backgrounds, theme fonts and a quiet grid. The football field colours
  bars by family (blue intrinsic, grey multiples, faint market references) and cuts extreme ranges at 3× the price
  with the true end labelled.

## PDF

A sell-side note: a navy masthead with the mark, date and report id on page 1; a rating box (rating, verdict, price,
fair value, upside); ruled section heads; running header and page-numbered footer on later pages; right-aligned
numeric columns.
