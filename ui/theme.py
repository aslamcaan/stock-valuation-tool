"""Design system: tokens, global CSS, small HTML components and the shared chart layout.

Direction (owner's choice): a refined dark research terminal. Number-first, quiet surfaces, one blue for the model's
own figures, green/red reserved for verdicts and gains/losses, amber for warnings. Figures use a monospaced face
with tabular numerals so columns align; prose uses IBM Plex Sans.
"""
from __future__ import annotations

import html
import re

BG, SURFACE, SURFACE_2, BORDER = "#0b0f14", "#11161d", "#171e27", "#232b35"
TEXT, MUTED, FAINT = "#e6edf3", "#9aa4af", "#6b7682"
GREEN, RED, AMBER, BLUE = "#3fb950", "#f85149", "#d29922", "#4c8dff"
FONT = "'IBM Plex Sans', 'Segoe UI', system-ui, sans-serif"
MONO = "'IBM Plex Mono', ui-monospace, SFMono-Regular, Menlo, monospace"
VERDICT_COLOUR = {"Undervalued": GREEN, "Overvalued": RED, "Fairly valued": AMBER}
RATING_COLOUR = {"Strong Buy": GREEN, "Buy": GREEN, "Hold": AMBER, "Sell": RED, "Strong Sell": RED}
FLAG_LABEL = {"hard_stop": "Hard stop", "red": "Red", "amber": "Amber", "info": "Info"}

# The mark: a rising bar chart inside a rounded square, drawn rather than a glyph.
LOGO = ("<svg width='{s}' height='{s}' viewBox='0 0 32 32' fill='none' aria-hidden='true'>"
        "<rect x='1' y='1' width='30' height='30' rx='8' fill='#132033' stroke='#2b4a78'/>"
        "<path d='M9 22V17M16 22V12M23 22V8' stroke='#4c8dff' stroke-width='3' stroke-linecap='round'/></svg>")

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500;600&display=swap');
:root {--vt-bg:#0b0f14; --vt-surface:#11161d; --vt-surface-2:#171e27; --vt-border:#232b35; --vt-text:#e6edf3;
  --vt-muted:#9aa4af; --vt-faint:#6b7682; --vt-green:#3fb950; --vt-red:#f85149; --vt-amber:#d29922; --vt-blue:#4c8dff;
  --vt-mono:'IBM Plex Mono', ui-monospace, SFMono-Regular, Menlo, monospace;
  --vt-ease: cubic-bezier(.16, 1, .3, 1);}
html, body, [data-testid="stAppViewContainer"], [data-testid="stSidebar"], button, input, textarea, select,
[data-testid="stMarkdownContainer"] {font-family: 'IBM Plex Sans', 'Segoe UI', system-ui, sans-serif;}
::selection {background: rgba(76,141,255,.35); color: #fff;}
* {scrollbar-width: thin; scrollbar-color: #2a333e transparent;}
::-webkit-scrollbar {width: 10px; height: 10px;} ::-webkit-scrollbar-thumb {background: #2a333e; border-radius: 6px;}
:focus-visible {outline: 2px solid var(--vt-blue) !important; outline-offset: 2px;}
input, textarea {caret-color: var(--vt-blue);}
a {color: #79a8ff; text-underline-offset: 3px;}
[data-testid="stHeader"] {background: transparent;}
[data-testid="stMainBlockContainer"], .block-container {max-width: 1240px; padding-top: 2.4rem; padding-bottom: 5rem;}
h1, h2, h3, h4, h5 {letter-spacing: -0.018em; font-weight: 650; text-wrap: balance;}
h1 {font-size: 1.9rem !important;}
h3 {font-size: 1.25rem !important; margin-top: 1.6rem !important;}
h4 {font-size: 1.02rem !important; margin: 1.9rem 0 .5rem !important; padding-bottom: .45rem;
    border-bottom: 1px solid var(--vt-border);}
h5 {font-size: .92rem !important; color: var(--vt-muted); margin-top: 1.2rem !important;}
[data-testid="stMarkdownContainer"] p, [data-testid="stMarkdownContainer"] li {line-height: 1.6; max-width: 78ch;}
[data-testid="stCaptionContainer"] {color: var(--vt-faint) !important; font-size: .8rem;}
[data-testid="stSidebar"] {background: #0d1218; border-right: 1px solid var(--vt-border);}
[data-testid="stSidebarNav"] a {border-radius: 8px;}
[data-testid="stExpander"] details {border: 1px solid var(--vt-border); border-radius: 10px; background: var(--vt-surface);}
[data-testid="stExpander"] summary {font-weight: 500; font-size: .92rem;}
[data-testid="stExpander"] summary:hover {color: var(--vt-text);}
[data-testid="stVerticalBlockBorderWrapper"] {border-color: var(--vt-border) !important; border-radius: 12px !important;}
.stTabs [data-baseweb="tab-list"] {gap: 1.75rem; border-bottom: 1px solid var(--vt-border); position: sticky; top: 0;
  z-index: 5; background: var(--vt-bg);}
.stTabs [data-baseweb="tab"] {padding: .7rem 0 .6rem; font-weight: 550; color: var(--vt-muted); font-size: .92rem;}
.stTabs [data-baseweb="tab"]:hover {color: var(--vt-text);}
.stTabs [aria-selected="true"] {color: var(--vt-text);}
.stTabs [data-baseweb="tab-highlight"] {background: var(--vt-blue); height: 2px;}
.stTabs [data-baseweb="tab-border"] {display: none;}
.stButton button, .stDownloadButton button, .stFormSubmitButton button {border-radius: 8px; border-color: var(--vt-border);
  font-weight: 500; transition: border-color .2s var(--vt-ease), background .2s var(--vt-ease);}
.stButton button:hover, .stDownloadButton button:hover, .stFormSubmitButton button:hover {border-color: #3a4655;
  background: var(--vt-surface-2); color: var(--vt-text);}
.stButton button[kind="primary"], .stFormSubmitButton button[kind="primaryFormSubmit"] {background: var(--vt-blue);
  border-color: var(--vt-blue); color: #fff;}
.stButton button[kind="primary"]:hover {background: #3d7ef0; border-color: #3d7ef0; color: #fff;}
[data-testid="stMetricValue"] {font-family: var(--vt-mono); font-size: 1.5rem; font-variant-numeric: tabular-nums;}
[data-testid="stMetricLabel"] p {color: var(--vt-muted); font-size: .8rem;}
[data-testid="stAlert"] {border-radius: 10px;}
[data-testid="stDataFrame"] {font-variant-numeric: tabular-nums;}
/* tables */
.vt-table {border-collapse: collapse; width: 100%; font-size: .84rem; margin: .3rem 0 .9rem;
  font-variant-numeric: tabular-nums;}
.vt-table th {text-align: right; padding: 7px 10px; border-bottom: 1px solid #2c3540; color: var(--vt-muted);
  font-weight: 500; font-size: .76rem; white-space: nowrap;}
.vt-table th:first-child, .vt-table td:first-child {text-align: left;}
.vt-table td {text-align: right; padding: 6px 10px; border-bottom: 1px solid #1a2129; font-family: var(--vt-mono);
  font-size: .79rem; color: #d7dee6;}
.vt-table td:first-child {font-family: inherit; font-size: .84rem; color: var(--vt-text);}
.vt-table tbody tr:hover td {background: var(--vt-surface-2);}
.vt-table td.tr {cursor: help; text-decoration: underline dotted #4a5563; text-underline-offset: 4px;}
.vt-table tr.sub td {color: var(--vt-muted); font-style: italic;}
.vt-table.text td {font-family: inherit; text-align: left; font-size: .84rem; vertical-align: top; line-height: 1.5;}
.vt-table.text th {text-align: left;}
.vt-scroll {overflow-x: auto;}
/* report header */
.vt-card {border: 1px solid var(--vt-border); border-radius: 12px; padding: 1.1rem 1.3rem; background: var(--vt-surface);}
.vt-head {border: 1px solid var(--vt-border); border-radius: 14px; background: var(--vt-surface);
  padding: 1.3rem 1.5rem 1.1rem; margin: .4rem 0 1.4rem; box-shadow: 0 12px 32px -18px rgba(0,0,0,.7);
  animation: vt-rise .5s var(--vt-ease) both;}
@keyframes vt-rise {from {opacity: .001; transform: translateY(6px);} to {opacity: 1; transform: none;}}
@media (prefers-reduced-motion: reduce) {.vt-head {animation: none;}}
.vt-id {display: flex; align-items: center; gap: .75rem; flex-wrap: wrap;}
.vt-ticker {font-family: var(--vt-mono); font-weight: 600; font-size: 1.45rem; letter-spacing: .01em;}
.vt-name {font-size: 1.02rem; color: var(--vt-muted); font-weight: 500;}
.vt-tag {font-size: .74rem; color: var(--vt-muted); border: 1px solid var(--vt-border); border-radius: 999px;
  padding: .12rem .6rem; white-space: nowrap;}
.vt-kpis {display: grid; grid-template-columns: 1fr 1.25fr .8fr 1.1fr 1fr; margin-top: 1.1rem;
  border-top: 1px solid var(--vt-border);}
.vt-kpi {padding: .9rem 1.1rem .2rem 0; min-width: 0;}
.vt-kpi + .vt-kpi {padding-left: 1.1rem; border-left: 1px solid var(--vt-border);}
.vt-kpi .l {font-size: .78rem; color: var(--vt-muted);}
.vt-kpi .v {font-family: var(--vt-mono); font-size: 1.6rem; font-weight: 600; margin-top: .2rem; white-space: nowrap;
  font-variant-numeric: tabular-nums; letter-spacing: -.01em;}
.vt-kpi .v.word {font-family: 'IBM Plex Sans', system-ui, sans-serif; font-size: 1.35rem; letter-spacing: -.015em; padding-top: .15rem;}
.vt-kpi .s {font-size: .78rem; color: var(--vt-faint); margin-top: .2rem; white-space: nowrap; overflow: hidden;
  text-overflow: ellipsis;}
.vt-kpi [title] {cursor: help;}
.vt-range {position: relative; height: 40px; margin: 1.5rem .4rem .1rem;}
.vt-range .track {position: absolute; top: 24px; left: 0; right: 0; height: 2px; background: #26303b;}
.vt-range .band {position: absolute; top: 20px; height: 10px; border-radius: 5px; background: rgba(76,141,255,.28);
  border: 1px solid rgba(76,141,255,.55);}
.vt-range .mark {position: absolute; top: 14px; width: 2px; height: 22px; border-radius: 1px; transform: translateX(-1px);}
.vt-range .lab {position: absolute; font-size: .72rem; transform: translateX(-50%); white-space: nowrap;
  font-family: var(--vt-mono);}
.vt-range .lab {top: -4px;} .vt-range .lab.l {transform: translateX(calc(-100% - 6px));}
.vt-range .lab.r {transform: translateX(6px);}
.vt-legend {display: flex; flex-wrap: wrap; gap: .3rem 1.4rem; font-size: .76rem; color: var(--vt-muted); margin: .25rem .4rem 0;}
.vt-legend .n {font-family: var(--vt-mono); color: var(--vt-text);}
.vt-legend i {display: inline-block; width: 18px; height: 8px; border-radius: 4px; margin-right: .4rem; vertical-align: 0;}
.vt-stats {display: flex; flex-wrap: wrap; gap: .45rem 2rem; font-size: .82rem; color: var(--vt-muted);
  margin-top: 1.1rem; padding-top: .9rem; border-top: 1px solid var(--vt-border);}
.vt-stats b {color: var(--vt-text); font-weight: 500;}
.vt-stats .n {font-family: var(--vt-mono); font-size: .8rem; color: var(--vt-text);}
.vt-chips {display: flex; flex-wrap: wrap; gap: .4rem; margin-top: .85rem;}
.vt-chip {font-size: .75rem; padding: .2rem .65rem; border-radius: 999px; border: 1px solid; white-space: nowrap;
  cursor: default;}
.vt-chip.hard_stop, .vt-chip.red {color: #ff9b95; border-color: rgba(248,81,73,.45); background: rgba(248,81,73,.08);}
.vt-chip.amber {color: #e8b84a; border-color: rgba(210,153,34,.45); background: rgba(210,153,34,.08);}
.vt-chip.info {color: var(--vt-muted); border-color: var(--vt-border);}
.vt-dot {display: inline-block; width: 7px; height: 7px; border-radius: 50%; margin-right: .45rem; vertical-align: 1px;}
.vt-verdict {font-size: 1.35rem; font-weight: 650; letter-spacing: -0.015em;}
.vt-muted {color: var(--vt-muted); font-size: .85rem;}
.vt-desk {font-family: var(--vt-mono); font-size: .84rem; line-height: 1.8;}
.vt-note {font-size: .84rem; color: var(--vt-muted); border: 1px solid var(--vt-border); border-radius: 10px;
  padding: .75rem 1rem; background: var(--vt-surface); margin: .6rem 0;}
/* landing and login */
.vt-hero {text-align: center; margin: 3.4rem 0 1.8rem;}
.vt-hero h1 {font-size: 2.35rem !important; margin: .9rem 0 .35rem; letter-spacing: -0.03em;}
.vt-hero p {color: var(--vt-muted); font-size: 1rem; margin: 0 auto; max-width: 52ch;}
.vt-login {text-align: center; margin: 13vh 0 1.6rem;}
.vt-login h1 {font-size: 1.8rem !important; margin: .9rem 0 .25rem;}
.vt-rc {padding: .1rem .1rem .2rem;}
.vt-rc .top {display: flex; justify-content: space-between; align-items: baseline;}
.vt-rc .t {font-family: var(--vt-mono); font-weight: 600; font-size: 1.02rem;}
.vt-rc .d {font-size: .75rem; color: var(--vt-faint); font-family: var(--vt-mono);}
.vt-rc .h {font-size: .84rem; margin-top: .45rem; color: var(--vt-muted);}
.vt-rc .h b {color: var(--vt-text); font-weight: 600;}
.vt-kpis.two {grid-template-columns: repeat(2, minmax(0, 1fr));}
.vt-kpis.two .vt-kpi:nth-child(odd) {border-left: none; padding-left: 0;}
.vt-kpis.two .vt-kpi:nth-child(n+3) {border-top: 1px solid var(--vt-border);}
@media (max-width: 900px) {.vt-kpis {grid-template-columns: repeat(2, minmax(0, 1fr));}
  .vt-kpi + .vt-kpi {border-left: none; padding-left: 0;} .vt-kpi:nth-child(even) {padding-left: 1rem;}}
</style>
"""


def esc(x) -> str:
    return html.escape(str(x), quote=True)


def chip(level: str, text: str, title: str = "") -> str:
    return (f"<span class='vt-chip {level}' title='{esc(title)}'>{esc(FLAG_LABEL.get(level, level))} · "
            f"{esc(text)}</span>")


def note(text: str) -> str:
    """A quiet notice for expected gaps (a desk that did not run, data the plan does not cover)."""
    return f"<div class='vt-note'>{esc(text)}</div>"


def dot(colour: str) -> str:
    return f"<span class='vt-dot' style='background:{colour}'></span>"


def install_dollar_guard() -> None:
    """Streamlit renders "$331 / $479" in markdown as LaTeX maths. The tool never uses maths, so every markdown,
    caption and alert body gets its "$" escaped. Raw HTML blocks (bodies starting with "<") are left alone: markdown
    does not process them, so maths cannot trigger there and a backslash would show."""
    from streamlit.delta_generator import DeltaGenerator
    if getattr(DeltaGenerator, "_vt_dollar_guard", False):
        return

    def escape(body):
        if not isinstance(body, str) or body.lstrip().startswith("<"):
            return body
        return re.sub(r"(?<!\\)\$", r"\\$", body)

    def wrap(name):
        orig = getattr(DeltaGenerator, name)

        def method(self, body, *a, **k):
            return orig(self, escape(body), *a, **k)
        method.__doc__ = orig.__doc__
        setattr(DeltaGenerator, name, method)
    import streamlit as st
    for name in ("markdown", "caption", "info", "warning", "error", "success"):
        wrap(name)
        # st.markdown & co. are bound to the main container at import, so they need the guard as well
        orig_st = getattr(st, name)
        setattr(st, name, (lambda f: lambda body, *a, **k: f(escape(body), *a, **k))(orig_st))
    DeltaGenerator._vt_dollar_guard = True


def plotly_layout(**kw) -> dict:
    """Shared chart styling: transparent background, the app's fonts, a quiet grid."""
    axis = dict(gridcolor="#1b222b", zerolinecolor=BORDER, linecolor=BORDER, tickfont=dict(family=MONO, size=11, color=MUTED),
                title=dict(font=dict(size=12, color=MUTED)))
    base = dict(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font=dict(family=FONT, size=12, color=TEXT),
                xaxis=dict(axis), yaxis=dict(axis, tickfont=dict(family=FONT, size=12, color=TEXT)),
                hoverlabel=dict(bgcolor=SURFACE_2, bordercolor=BORDER, font=dict(family=FONT, size=12, color=TEXT)),
                margin=dict(l=10, r=10, t=30, b=10), showlegend=False)
    for k, v in kw.items():
        base[k] = {**base[k], **v} if isinstance(v, dict) and isinstance(base.get(k), dict) else v
    return base
