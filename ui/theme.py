"""Design system: tokens, global CSS, small HTML components and the shared chart layout.

Direction (owner's choice): a black and orange research terminal. Warm black surfaces, cream text (never pure white),
one orange for the model's own figures, focus and primary actions; green/red reserved for verdicts and gains/losses,
yellow for warnings. Headings use Archivo (expanded), prose IBM Plex Sans, figures IBM Plex Mono with tabular numerals.

Motion: one signature, the orange scan (a line sweeping a chart: the landing hero and the analysis screen). Pages and
tab panels rise in once; figures in the report header count up; nothing loops except while a report is running.
Streamlit patches re-rendered HTML in place, so animations never carry per-render timing.
"""
from __future__ import annotations

import html
import re

BG, SURFACE, SURFACE_2, BORDER = "#0a0908", "#13110e", "#1b1814", "#2b2520"
TEXT, MUTED, FAINT = "#ede4d3", "#a39a8a", "#857b6e"
ACCENT, ACCENT_2 = "#ff7a1a", "#ffa45c"
GREEN, RED, AMBER = "#6fcf86", "#f2604f", "#e9b949"
FONT = "'IBM Plex Sans', 'Segoe UI', system-ui, sans-serif"
DISPLAY = "'Archivo', 'IBM Plex Sans', system-ui, sans-serif"
MONO = "'IBM Plex Mono', ui-monospace, SFMono-Regular, Menlo, monospace"
VERDICT_COLOUR = {"Undervalued": GREEN, "Overvalued": RED, "Fairly valued": AMBER}
RATING_COLOUR = {"Strong Buy": GREEN, "Buy": GREEN, "Hold": AMBER, "Sell": RED, "Strong Sell": RED}
RATINGS = ["Strong Buy", "Buy", "Hold", "Sell", "Strong Sell"]
FLAG_LABEL = {"hard_stop": "Hard stop", "red": "Red", "amber": "Amber", "info": "Info"}

# The mark: a rising bar chart inside a rounded square, drawn rather than a glyph.
LOGO = ("<svg width='{s}' height='{s}' viewBox='0 0 32 32' fill='none' aria-hidden='true'>"
        "<rect x='1' y='1' width='30' height='30' rx='8' fill='#1c130b' stroke='#5a3415'/>"
        "<path d='M9 22V17M16 22V12M23 22V8' stroke='#ff7a1a' stroke-width='3' stroke-linecap='round'/></svg>")

# Authored icons (one stroke weight), used inside HTML blocks.
ICON = {
    "check": "<svg viewBox='0 0 16 16' width='14' height='14' fill='none' aria-hidden='true'><path d='M3.5 8.5l3 3 6-7'"
             " stroke='currentColor' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'/></svg>",
    "cross": "<svg viewBox='0 0 16 16' width='13' height='13' fill='none' aria-hidden='true'><path d='M4 4l8 8M12 4l-8 8'"
             " stroke='currentColor' stroke-width='2' stroke-linecap='round'/></svg>",
    "dash": "<svg viewBox='0 0 16 16' width='13' height='13' fill='none' aria-hidden='true'><path d='M4 8h8'"
            " stroke='currentColor' stroke-width='2' stroke-linecap='round'/></svg>",
    "arrow": "<svg viewBox='0 0 16 16' width='14' height='14' fill='none' aria-hidden='true'><path d='M3 8h10M9 4l4 4-4 4'"
             " stroke='currentColor' stroke-width='1.8' stroke-linecap='round' stroke-linejoin='round'/></svg>",
}

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Archivo:wdth,wght@62..125,500..800&family=IBM+Plex+Sans:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500;600&display=swap');
:root {--vt-bg:#0a0908; --vt-surface:#13110e; --vt-surface-2:#1b1814; --vt-border:#2b2520; --vt-border-2:#3d342c;
  --vt-text:#ede4d3; --vt-muted:#a39a8a; --vt-faint:#857b6e; --vt-accent:#ff7a1a; --vt-accent-2:#ffa45c;
  --vt-accent-dim:rgba(255,122,26,.13); --vt-green:#6fcf86; --vt-red:#f2604f; --vt-amber:#e9b949;
  --vt-mono:'IBM Plex Mono', ui-monospace, SFMono-Regular, Menlo, monospace;
  --vt-display:'Archivo', 'IBM Plex Sans', system-ui, sans-serif;
  --vt-ease: cubic-bezier(.16, 1, .3, 1); --vt-ease-io: cubic-bezier(.65, 0, .35, 1);}
html, body, [data-testid="stAppViewContainer"], button, input, textarea, select,
[data-testid="stMarkdownContainer"] {font-family: 'IBM Plex Sans', 'Segoe UI', system-ui, sans-serif;}
body, .stApp {color: var(--vt-text);}
.stApp {background: radial-gradient(1100px 520px at 50% -160px, rgba(255,122,26,.11), transparent 70%), var(--vt-bg);}
/* graph-paper grid, fading out from the top */
[data-testid="stAppViewContainer"]::before {content: ''; position: fixed; inset: 0; pointer-events: none; z-index: 0;
  background-image: linear-gradient(rgba(237,228,211,.035) 1px, transparent 1px),
                    linear-gradient(90deg, rgba(237,228,211,.035) 1px, transparent 1px);
  background-size: 56px 56px; -webkit-mask-image: radial-gradient(ellipse 80% 60% at 50% 0%, #000 10%, transparent 75%);
  mask-image: radial-gradient(ellipse 80% 60% at 50% 0%, #000 10%, transparent 75%);}
[data-testid="stMain"] {position: relative; z-index: 1;}
::selection {background: rgba(255,122,26,.38); color: #fff6ea;}
* {scrollbar-width: thin; scrollbar-color: #3a3129 transparent;}
::-webkit-scrollbar {width: 10px; height: 10px;} ::-webkit-scrollbar-thumb {background: #3a3129; border-radius: 6px;}
:focus-visible {outline: 2px solid var(--vt-accent) !important; outline-offset: 2px;}
input, textarea {caret-color: var(--vt-accent);}
a {color: var(--vt-accent-2); text-underline-offset: 3px;}
[data-testid="stMainBlockContainer"], .block-container {max-width: 1240px; padding-top: 3.4rem; padding-bottom: 5rem;}
h1, h2, h3, h4, h5 {letter-spacing: -0.02em; font-weight: 700; text-wrap: balance; color: var(--vt-text);}
h1, h2, h3 {font-family: var(--vt-display) !important; font-stretch: 112%;}
h1 {font-size: 2rem !important; font-weight: 800 !important;}
h3 {font-size: 1.25rem !important; margin-top: 1.6rem !important;}
h4 {font-size: 1rem !important; margin: 2rem 0 .7rem !important; padding-bottom: .5rem; font-weight: 650 !important;
    border-bottom: 1px solid var(--vt-border);}
h5 {font-size: .9rem !important; color: var(--vt-muted); margin-top: 1.2rem !important;}
[data-testid="stMarkdownContainer"] p, [data-testid="stMarkdownContainer"] li {line-height: 1.62; max-width: 78ch;}
[data-testid="stMarkdownContainer"] strong {color: #fff3e2; font-weight: 600;}
[data-testid="stCaptionContainer"] {color: var(--vt-faint) !important; font-size: .8rem;}

/* --- entrance: each page's blocks rise in once, staggered; tab panels on every switch ----------------------------- */
@keyframes vt-in {from {opacity: 0; transform: translateY(12px); filter: blur(3px);} to {opacity: 1; transform: none; filter: none;}}
[data-testid="stMainBlockContainer"] > div > [data-testid="stVerticalBlock"] > div {animation: vt-in .7s var(--vt-ease) both;}
[data-testid="stMainBlockContainer"] > div > [data-testid="stVerticalBlock"] > div:nth-child(2) {animation-delay: .05s;}
[data-testid="stMainBlockContainer"] > div > [data-testid="stVerticalBlock"] > div:nth-child(3) {animation-delay: .1s;}
[data-testid="stMainBlockContainer"] > div > [data-testid="stVerticalBlock"] > div:nth-child(4) {animation-delay: .15s;}
[data-testid="stMainBlockContainer"] > div > [data-testid="stVerticalBlock"] > div:nth-child(5) {animation-delay: .2s;}
[data-testid="stMainBlockContainer"] > div > [data-testid="stVerticalBlock"] > div:nth-child(n+6) {animation-delay: .25s;}
[data-baseweb="tab-panel"] {animation: vt-in .5s var(--vt-ease) both;}

/* --- top navigation ------------------------------------------------------------------------------------------- */
[data-testid="stHeader"] {background: rgba(10,9,8,.78); backdrop-filter: blur(14px) saturate(140%);
  -webkit-backdrop-filter: blur(14px) saturate(140%); border-bottom: 1px solid var(--vt-border);}
[data-testid="stTopNavLink"] {position: relative; border-radius: 8px !important;
  transition: color .25s var(--vt-ease), background .25s var(--vt-ease);}
[data-testid="stTopNavLink"] span, [data-testid="stTopNavLink"] p {color: var(--vt-muted); font-weight: 550;}
[data-testid="stTopNavLink"]:hover span, [data-testid="stTopNavLink"]:hover p {color: var(--vt-text);}
[data-testid="stTopNavLink"]::after {content: ''; position: absolute; left: 14%; right: 14%; bottom: -1px; height: 2px;
  border-radius: 2px; background: var(--vt-accent); transform: scaleX(0); transform-origin: center;
  transition: transform .35s var(--vt-ease);}
[data-testid="stTopNavLink"]:hover::after {transform: scaleX(.45);}
[data-testid="stTopNavLink"][aria-current="page"]::after {transform: scaleX(1); box-shadow: 0 0 10px rgba(255,122,26,.7);}
[data-testid="stTopNavLink"][aria-current="page"] span, [data-testid="stTopNavLink"][aria-current="page"] p
  {color: var(--vt-text);}
[data-testid="stTopNavLink"] [data-testid="stIconMaterial"] {color: var(--vt-faint);}
[data-testid="stTopNavLink"][aria-current="page"] [data-testid="stIconMaterial"] {color: var(--vt-accent);}

/* --- controls --------------------------------------------------------------------------------------------------- */
[data-testid="stExpander"] details {border: 1px solid var(--vt-border); border-radius: 10px; background: var(--vt-surface);
  transition: border-color .25s var(--vt-ease);}
[data-testid="stExpander"] details:hover {border-color: var(--vt-border-2);}
[data-testid="stExpander"] summary {font-weight: 500; font-size: .92rem;}
[data-testid="stVerticalBlockBorderWrapper"] {border-color: var(--vt-border) !important; border-radius: 12px !important;}
.stTabs [data-baseweb="tab-list"] {gap: 1.6rem; border-bottom: 1px solid var(--vt-border); position: sticky; top: 3.6rem;
  z-index: 5; background: rgba(10,9,8,.9); backdrop-filter: blur(10px); -webkit-backdrop-filter: blur(10px);}
.stTabs [data-baseweb="tab"] {padding: .75rem 0 .65rem; font-weight: 550; color: var(--vt-muted); font-size: .92rem;
  transition: color .25s var(--vt-ease);}
.stTabs [data-baseweb="tab"]:hover {color: var(--vt-text);}
.stTabs [aria-selected="true"] {color: var(--vt-text);}
.stTabs [data-baseweb="tab-highlight"] {background: var(--vt-accent); height: 2px; border-radius: 2px;
  box-shadow: 0 2px 12px rgba(255,122,26,.6);}
.stTabs [data-baseweb="tab-border"] {display: none;}
.stButton button, .stDownloadButton button, .stFormSubmitButton button {border-radius: 9px; border-color: var(--vt-border-2);
  background: var(--vt-surface); font-weight: 550; color: var(--vt-text);
  transition: border-color .2s var(--vt-ease), background .2s var(--vt-ease), transform .16s var(--vt-ease),
              box-shadow .3s var(--vt-ease);}
.stButton button:hover, .stDownloadButton button:hover, .stFormSubmitButton button:hover {border-color: var(--vt-accent);
  background: var(--vt-surface-2); color: var(--vt-text); box-shadow: 0 6px 18px -10px rgba(255,122,26,.7);}
.stButton button:active, .stDownloadButton button:active, .stFormSubmitButton button:active {transform: scale(.97);}
.stButton button[kind="primary"], .stFormSubmitButton button[kind="primaryFormSubmit"] {background: var(--vt-accent);
  border-color: var(--vt-accent); color: #1a0c02; font-weight: 650;}
.stButton button[kind="primary"]:hover, .stFormSubmitButton button[kind="primaryFormSubmit"]:hover
  {background: #ff8a33; border-color: #ff8a33; color: #1a0c02; box-shadow: 0 10px 28px -10px rgba(255,122,26,.85);}
.stButton button[kind="primary"] p, .stFormSubmitButton button[kind="primaryFormSubmit"] p {color: #1a0c02;}
[data-testid="stMetricValue"] {font-family: var(--vt-mono); font-size: 1.5rem; font-variant-numeric: tabular-nums;}
[data-testid="stMetricLabel"] p {color: var(--vt-muted); font-size: .8rem;}
[data-testid="stAlert"] {border-radius: 10px;}
[data-testid="stDataFrame"] {font-variant-numeric: tabular-nums;}

/* --- tables ----------------------------------------------------------------------------------------------------- */
.vt-table {border-collapse: collapse; width: 100%; font-size: .84rem; margin: .3rem 0 .9rem;
  font-variant-numeric: tabular-nums;}
.vt-table th {text-align: right; padding: 8px 10px; border-bottom: 1px solid var(--vt-border-2); color: var(--vt-muted);
  font-weight: 500; font-size: .76rem; white-space: nowrap;}
.vt-table th:first-child, .vt-table td:first-child {text-align: left;}
.vt-table td {text-align: right; padding: 7px 10px; border-bottom: 1px solid #1f1b17; font-family: var(--vt-mono);
  font-size: .79rem; color: #e2d8c6; transition: background .15s;}
.vt-table td:first-child {font-family: inherit; font-size: .84rem; color: var(--vt-text);}
.vt-table tbody tr:hover td {background: var(--vt-accent-dim);}
.vt-table td.tr {cursor: help; text-decoration: underline dotted #5c5045; text-underline-offset: 4px;}
.vt-table tr.sub td {color: var(--vt-muted); font-style: italic;}
.vt-table.text td {font-family: inherit; text-align: left; font-size: .84rem; vertical-align: top; line-height: 1.5;}
.vt-table.text th {text-align: left;}
.vt-scroll {overflow-x: auto;}

/* --- report header ---------------------------------------------------------------------------------------------- */
.vt-card {border: 1px solid var(--vt-border); border-radius: 12px; padding: 1.1rem 1.3rem; background: var(--vt-surface);}
.vt-head {position: relative; overflow: hidden; border: 1px solid var(--vt-border); border-radius: 18px;
  background: linear-gradient(180deg, #16120e 0%, var(--vt-surface) 55%);
  padding: 1.5rem 1.7rem 1.2rem; margin: .4rem 0 1.2rem; box-shadow: 0 24px 60px -30px rgba(0,0,0,.9);}
.vt-head::before {content: ''; position: absolute; inset: 0 0 auto 0; height: 1px;
  background: linear-gradient(90deg, transparent, rgba(255,122,26,.75), transparent);
  animation: vt-sheen 1.6s var(--vt-ease) .2s both;}
@keyframes vt-sheen {from {transform: translateX(-100%); opacity: 0;} to {transform: none; opacity: 1;}}
.vt-head .top {display: flex; justify-content: space-between; align-items: flex-start; gap: 1.5rem; flex-wrap: wrap;}
.vt-ticker {font-family: var(--vt-display); font-stretch: 125%; font-weight: 800; font-size: 2.6rem; line-height: 1;
  letter-spacing: -.03em; color: var(--vt-text);}
.vt-id {display: flex; align-items: baseline; gap: .75rem; flex-wrap: wrap;}
.vt-id .vt-ticker {font-size: 1.9rem;} .vt-id .vt-name {margin-top: 0;}
.vt-name {font-size: 1.05rem; color: var(--vt-muted); font-weight: 500; margin-top: .45rem;}
.vt-tags {display: flex; gap: .4rem; flex-wrap: wrap; margin-top: .7rem;}
.vt-tag {font-size: .74rem; color: var(--vt-muted); border: 1px solid var(--vt-border-2); border-radius: 999px;
  padding: .14rem .62rem; white-space: nowrap;}
.vt-rating {display: flex; align-items: center; gap: 1rem;}
.vt-rating .ring {position: relative; width: 84px; height: 84px; flex: none;}
.vt-rating .ring svg {transform: rotate(-90deg);}
.vt-rating .ring .arc {stroke-dasharray: var(--len) 999; animation: vt-arc 1.6s var(--vt-ease) .25s both;}
@keyframes vt-arc {from {stroke-dasharray: 0 999;}}
.vt-rating .ring .sc {position: absolute; inset: 0; display: grid; place-content: center; text-align: center;
  font-family: var(--vt-mono); font-weight: 600; font-size: 1.15rem; line-height: 1.1;}
.vt-rating .ring .sc small {display: block; font-size: .62rem; color: var(--vt-faint); font-weight: 400;}
.vt-rating .w {font-family: var(--vt-display); font-stretch: 115%; font-weight: 800; font-size: 1.7rem; line-height: 1.05;}
.vt-rating .c {font-size: .8rem; color: var(--vt-muted); margin-top: .3rem;}
.vt-kpis {display: grid; grid-template-columns: 1fr 1.25fr .8fr 1.25fr; margin-top: 1.3rem;
  border-top: 1px solid var(--vt-border);}
.vt-kpi {padding: 1rem 1.1rem .2rem 0; min-width: 0;}
.vt-kpi + .vt-kpi {padding-left: 1.1rem; border-left: 1px solid var(--vt-border);}
.vt-kpi .l {font-size: .78rem; color: var(--vt-muted);}
.vt-kpi .v {font-family: var(--vt-mono); font-size: 1.75rem; font-weight: 600; margin-top: .2rem; white-space: nowrap;
  font-variant-numeric: tabular-nums; letter-spacing: -.02em;}
.vt-kpi .v.word {font-family: var(--vt-display); font-stretch: 110%; font-weight: 750; font-size: 1.45rem;
  letter-spacing: -.02em; padding-top: .2rem;}
.vt-kpi .s {font-size: .78rem; color: var(--vt-faint); margin-top: .25rem; white-space: nowrap; overflow: hidden;
  text-overflow: ellipsis;}
.vt-kpi [title] {cursor: help;}
/* counting figures: the integer and decimal parts are animated custom properties shown through CSS counters */
@property --vt-i {syntax: '<integer>'; initial-value: 0; inherits: false;}
@property --vt-f {syntax: '<integer>'; initial-value: 0; inherits: false;}
.vt-n {--vt-i: var(--ti); --vt-f: var(--tf); counter-reset: i var(--vt-i) f var(--vt-f);
  animation: vt-count 1.5s var(--vt-ease) .15s both;}
.vt-n::after {content: attr(data-pre) counter(i) "." counter(f, decimal-leading-zero) attr(data-post);}
.vt-n.d1::after {content: attr(data-pre) counter(i) "." counter(f) attr(data-post);}
@keyframes vt-count {from {--vt-i: 0; --vt-f: 0;}}
.vt-range {position: relative; height: 44px; margin: 1.6rem .4rem .1rem;}
.vt-range .track {position: absolute; top: 26px; left: 0; right: 0; height: 2px; background: #2e2722; border-radius: 2px;}
.vt-range .band {position: absolute; top: 21px; height: 12px; border-radius: 6px; background: rgba(255,122,26,.22);
  border: 1px solid rgba(255,122,26,.6); transform-origin: left center; animation: vt-grow 1.1s var(--vt-ease) .3s both;}
@keyframes vt-grow {from {transform: scaleX(0); opacity: 0;}}
.vt-range .mark {position: absolute; top: 15px; width: 2px; height: 24px; border-radius: 1px; transform: translateX(-1px);
  animation: vt-drop .8s var(--vt-ease) .9s both;}
.vt-range .mark.fv {box-shadow: 0 0 14px 1px rgba(255,122,26,.65);}
@keyframes vt-drop {from {opacity: 0; transform: translate(-1px, -10px);}}
.vt-range .lab {position: absolute; font-size: .74rem; transform: translateX(-50%); white-space: nowrap;
  font-family: var(--vt-mono); top: -2px; animation: vt-fade .6s var(--vt-ease) 1.1s both;}
@keyframes vt-fade {from {opacity: 0;}}
.vt-range .lab.l {transform: translateX(calc(-100% - 6px));}
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
.vt-chip.hard_stop, .vt-chip.red {color: #ff9d90; border-color: rgba(242,96,79,.45); background: rgba(242,96,79,.08);}
.vt-chip.amber {color: #f0cc6e; border-color: rgba(233,185,73,.45); background: rgba(233,185,73,.08);}
.vt-chip.info {color: var(--vt-muted); border-color: var(--vt-border-2);}
.vt-dot {display: inline-block; width: 7px; height: 7px; border-radius: 50%; margin-right: .45rem; vertical-align: 1px;}
.vt-muted {color: var(--vt-muted); font-size: .85rem;}
.vt-desk {font-family: var(--vt-mono); font-size: .84rem; line-height: 1.8;}
.vt-note.warn {color: #e9dcc0; border-color: rgba(233,185,73,.4); background: rgba(233,185,73,.06); margin: 0 0 1.2rem;}
.vt-note.warn b {color: var(--vt-amber);}
[data-testid='stAlertContentWarning'], [data-testid='stAlertContentInfo'], [data-testid='stAlertContentError'] {color: var(--vt-text);}
[data-testid='stAlert'] > div {border: 1px solid var(--vt-border-2); background: var(--vt-surface) !important;}
.vt-guide {display: flex; flex-direction: column; gap: .2rem; font-size: .86rem; line-height: 1.58; color: var(--vt-muted);
  border-left: 2px solid rgba(255,122,26,.55); background: rgba(255,122,26,.04); border-radius: 0 10px 10px 0;
  padding: .6rem .95rem; margin: .35rem 0 1.1rem; max-width: 96ch;}
.vt-guide b {font-family: var(--vt-mono); font-size: .68rem; letter-spacing: .08em; text-transform: uppercase;
  color: var(--vt-accent); font-weight: 600;}
.vt-kv {display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: .8rem 1.4rem; margin: .6rem 0 1rem;}
.vt-kv div {border-top: 1px solid var(--vt-border); padding-top: .55rem;}
.vt-kv .l {font-size: .74rem; color: var(--vt-faint);}
.vt-kv .v {font-family: var(--vt-mono); font-size: 1.08rem; color: var(--vt-text); font-weight: 600; margin: .1rem 0;}
.vt-kv .v.acc {color: var(--vt-accent);}
.vt-kv .s {font-size: .76rem; color: var(--vt-muted); line-height: 1.45;}
.vt-note {font-size: .84rem; color: var(--vt-muted); border: 1px solid var(--vt-border); border-radius: 10px;
  padding: .75rem 1rem; background: var(--vt-surface); margin: .6rem 0;}

/* --- why this rating: reasons and the rubric ------------------------------------------------------------------------ */
.vt-why {display: grid; grid-template-columns: 1.25fr 1fr; gap: 1.2rem; margin: 0 0 1.4rem;}
.vt-panel {border: 1px solid var(--vt-border); border-radius: 14px; background: var(--vt-surface); padding: 1.1rem 1.3rem;}
.vt-panel h6 {font-family: var(--vt-display); font-stretch: 110%; font-size: .95rem; font-weight: 700; margin: 0 0 .8rem;
  color: var(--vt-text); letter-spacing: -.01em; padding: 0;}
.vt-reasons {list-style: none; margin: 0; padding: 0; counter-reset: r;}
.vt-reasons li {position: relative; padding: .15rem 0 .75rem 2.2rem; line-height: 1.55; font-size: .92rem;
  counter-increment: r; animation: vt-in .6s var(--vt-ease) both; margin: 0;}
.vt-reasons li:nth-child(2) {animation-delay: .08s;} .vt-reasons li:nth-child(3) {animation-delay: .16s;}
.vt-reasons li:nth-child(4) {animation-delay: .24s;}
.vt-reasons li::before {content: counter(r); position: absolute; left: 0; top: .15rem; width: 1.45rem; height: 1.45rem;
  border-radius: 50%; display: grid; place-items: center; font-family: var(--vt-mono); font-size: .72rem;
  color: var(--vt-accent); border: 1px solid rgba(255,122,26,.5); background: var(--vt-accent-dim);}
.vt-rubric {display: grid; gap: .55rem;}
.vt-rubric .row {display: grid; grid-template-columns: minmax(0, 1.3fr) minmax(0, 1fr) 2rem; gap: .7rem; align-items: center;
  font-size: .82rem;}
.vt-rubric .row .k {color: var(--vt-muted); white-space: nowrap; overflow: hidden; text-overflow: ellipsis;}
.vt-rubric .row .k small {color: var(--vt-faint); font-family: var(--vt-mono); margin-left: .3rem;}
.vt-rubric .bar {height: 6px; border-radius: 3px; background: #2a231d; overflow: hidden;}
.vt-rubric .bar i {display: block; height: 100%; border-radius: 3px; background: linear-gradient(90deg, #b8520c, var(--vt-accent));
  transform-origin: left; animation: vt-grow 1s var(--vt-ease) both;}
.vt-rubric .row .s {font-family: var(--vt-mono); text-align: right; color: var(--vt-text);}
.vt-rubric .total {display: flex; justify-content: space-between; border-top: 1px solid var(--vt-border); padding-top: .6rem;
  margin-top: .2rem; font-size: .84rem; color: var(--vt-muted);}
.vt-rubric .total b {font-family: var(--vt-mono); color: var(--vt-text); font-weight: 600;}

/* --- investment view ------------------------------------------------------------------------------------------------ */
.vt-thesis {font-size: 1.12rem; line-height: 1.65; color: var(--vt-text); max-width: 72ch; margin: .2rem 0 1.2rem;
  padding: .2rem 0 .2rem 1.2rem; position: relative;}
.vt-thesis::before {content: ''; position: absolute; left: 0; top: .35rem; bottom: .35rem; width: 1px;
  background: linear-gradient(180deg, var(--vt-accent), transparent);}
.vt-duel {display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; margin: .4rem 0 1.2rem;}
.vt-duel .side {border: 1px solid var(--vt-border); border-radius: 14px; padding: 1rem 1.15rem; background: var(--vt-surface);
  position: relative; transition: border-color .3s var(--vt-ease), transform .3s var(--vt-ease);}
.vt-duel .side:hover {transform: translateY(-2px); border-color: var(--vt-border-2);}
.vt-duel .side.won {border-color: rgba(255,122,26,.55); background: linear-gradient(180deg, rgba(255,122,26,.07), var(--vt-surface) 60%);}
.vt-duel .side h6 {font-family: var(--vt-display); font-stretch: 110%; font-size: .95rem; margin: 0 0 .5rem; padding: 0;
  display: flex; justify-content: space-between; align-items: center; color: var(--vt-text);}
.vt-duel .side .badge {font-family: 'IBM Plex Sans', sans-serif; font-size: .7rem; font-weight: 600; color: #1a0c02;
  background: var(--vt-accent); border-radius: 999px; padding: .12rem .55rem;}
.vt-duel .side p {font-size: .88rem; line-height: 1.55; color: #ddd3c1; margin: 0;}
.vt-checks {list-style: none; padding: 0; margin: .2rem 0 1rem;}
.vt-checks li {position: relative; padding: .4rem 0 .4rem 1.8rem; line-height: 1.55; font-size: .92rem; margin: 0;
  border-bottom: 1px dashed #2a241f;}
.vt-checks li svg {position: absolute; left: 0; top: .62rem; color: var(--vt-accent);}
.vt-timeline {position: relative; margin: .5rem 0 1rem; padding-left: 1.4rem;}
.vt-timeline::before {content: ''; position: absolute; left: .32rem; top: .4rem; bottom: .4rem; width: 1px;
  background: linear-gradient(180deg, var(--vt-accent), var(--vt-border));}
.vt-timeline .ev {position: relative; padding: 0 0 .9rem;}
.vt-timeline .ev::before {content: ''; position: absolute; left: -1.33rem; top: .38rem; width: 9px; height: 9px;
  border-radius: 50%; background: var(--vt-bg); border: 2px solid var(--vt-accent);}
.vt-timeline .ev b {font-weight: 600;}
.vt-timeline .ev .d {font-family: var(--vt-mono); font-size: .76rem; color: var(--vt-accent-2); margin-left: .5rem;}
.vt-timeline .ev p {margin: .15rem 0 0; font-size: .86rem; color: var(--vt-muted);}
.vt-sec-n {font-family: var(--vt-mono); font-size: .8rem; color: var(--vt-accent); font-weight: 500;
  margin-right: .5rem;}
.vt-sub {font-family: var(--vt-display); font-stretch: 110%; font-weight: 700; font-size: .95rem; margin: 1.3rem 0 .5rem;
  color: var(--vt-text);}

/* --- analysis screen ------------------------------------------------------------------------------------------------ */
.vt-run {border: 1px solid var(--vt-border); border-radius: 20px; overflow: hidden; background: var(--vt-surface);
  box-shadow: 0 30px 70px -36px rgba(0,0,0,.95);}
.vt-run .scope {position: relative; height: 200px; border-bottom: 1px solid var(--vt-border);
  background: radial-gradient(600px 180px at 50% 120%, rgba(255,122,26,.14), transparent 70%), #0e0c0a; overflow: hidden;}
.vt-run .scope svg {position: absolute; inset: 0; width: 100%; height: 100%;}
.vt-run .scope .line {stroke-dasharray: 1400; animation: vt-draw 6s linear infinite;}
@keyframes vt-draw {0% {stroke-dashoffset: 1400; opacity: 1;} 70% {stroke-dashoffset: 0; opacity: 1;}
  100% {stroke-dashoffset: 0; opacity: 0;}}
.vt-run .scope svg.bars {left: 30%; width: 56%; top: 1.2rem; height: calc(100% - 1.5rem);}
.vt-run .scope .beam {position: absolute; top: 0; bottom: 0; width: 90px; left: -90px;
  background: linear-gradient(90deg, transparent, rgba(255,122,26,.10) 75%, rgba(255,164,92,.55) 99%, transparent);
  border-right: 1px solid rgba(255,190,140,.7);
  animation: vt-beam 3.2s var(--vt-ease-io) infinite;}
@keyframes vt-beam {to {left: 100%;}}
.vt-run .scope .meta {position: absolute; left: 1.4rem; bottom: 1.1rem; right: 1.4rem; display: flex;
  justify-content: space-between; align-items: flex-end; gap: 1rem;}
.vt-run .scope .tk {font-family: var(--vt-mono); font-size: .8rem; color: var(--vt-accent-2); margin-bottom: .35rem;}
.vt-run .scope .pct {font-family: var(--vt-display); font-stretch: 125%; font-weight: 800; font-size: 3.4rem; line-height: .9;
  color: var(--vt-text); font-variant-numeric: tabular-nums; letter-spacing: -.03em;}
.vt-run .scope .pct small {font-size: 1.3rem; color: var(--vt-accent); margin-left: .15rem;}
.vt-run .scope .clock {position: absolute; top: .9rem; right: 1.4rem; font-family: var(--vt-mono); font-size: .8rem;
  color: var(--vt-muted); text-align: right; line-height: 1.5;}
.vt-run .scope .clock b {color: var(--vt-text); font-weight: 500;}
.vt-run .bar {height: 3px; background: #241e19;}
.vt-run .bar i {display: block; height: 100%; background: linear-gradient(90deg, #b8520c, var(--vt-accent), #ffc08a);
  box-shadow: 0 0 16px rgba(255,122,26,.8);}
.vt-run .now {padding: 1.1rem 1.4rem .3rem; display: flex; gap: .9rem; align-items: baseline; flex-wrap: wrap;}
.vt-run .now .who {font-family: var(--vt-display); font-stretch: 110%; font-weight: 750; font-size: 1.15rem;}
.vt-run .now .what {color: var(--vt-muted); font-size: .92rem;}
.vt-run .about {padding: 0 1.4rem 1rem; font-size: .84rem; color: var(--vt-faint); max-width: 90ch; line-height: 1.55;}
.vt-flow {display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: .6rem; padding: .6rem 1.4rem 1.4rem;}
.vt-node {position: relative; border: 1px solid var(--vt-border); border-radius: 12px; padding: .7rem .8rem .75rem;
  background: #0f0d0b; min-width: 0;}
.vt-node .hd {display: flex; align-items: center; gap: .5rem;}
.vt-node .ic {width: 22px; height: 22px; border-radius: 50%; display: grid; place-items: center; flex: none;
  border: 1px solid var(--vt-border-2); color: var(--vt-faint); position: relative;}
.vt-node .nm {font-weight: 600; font-size: .86rem; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;}
.vt-node .ms {font-size: .76rem; color: var(--vt-faint); margin-top: .4rem; line-height: 1.4; height: 2.8em; overflow: hidden;
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical;}
.vt-node.done {border-color: rgba(255,122,26,.35);}
.vt-node.done .ic {background: var(--vt-accent); border-color: var(--vt-accent); color: #1a0c02;}
.vt-node.done .ms {color: var(--vt-muted);}
.vt-node.running {border-color: var(--vt-accent); background: linear-gradient(180deg, rgba(255,122,26,.10), #0f0d0b 70%);}
.vt-node.running .ic {border-color: transparent;}
.vt-node.running .ic::before {content: ''; position: absolute; inset: -1px; border-radius: 50%;
  border: 2px solid transparent; border-top-color: var(--vt-accent); border-right-color: var(--vt-accent);
  animation: vt-spin .9s linear infinite;}
.vt-node.running .ic::after {content: ''; width: 6px; height: 6px; border-radius: 50%; background: var(--vt-accent);
  animation: vt-pulse 1.4s ease-in-out infinite;}
.vt-node.running .ms {color: var(--vt-text);}
.vt-node.running::after {content: ''; position: absolute; left: 12px; right: 12px; bottom: -1px; height: 2px;
  background: linear-gradient(90deg, transparent, var(--vt-accent), transparent); background-size: 50% 100%;
  background-repeat: no-repeat; animation: vt-slide 1.6s var(--vt-ease-io) infinite;}
@keyframes vt-slide {from {background-position: -100% 0;} to {background-position: 200% 0;}}
@keyframes vt-spin {to {transform: rotate(360deg);}}
@keyframes vt-pulse {50% {transform: scale(.5); opacity: .5;}}
.vt-node.failed {border-color: rgba(242,96,79,.5);}
.vt-node.failed .ic {color: var(--vt-red); border-color: rgba(242,96,79,.6);}
.vt-node.skipped {opacity: .55;}

/* --- landing ---------------------------------------------------------------------------------------------------- */
.vt-hero {position: relative; margin: 0 0 1.4rem; padding: 2.6rem 2.4rem 2.2rem; border: 1px solid var(--vt-border);
  border-radius: 22px; overflow: hidden; background: #0e0c0a; min-height: 300px;}
.vt-hero svg.chart {position: absolute; right: 0; bottom: 0; width: 56%; height: 74%;
  -webkit-mask-image: linear-gradient(90deg, transparent, rgba(0,0,0,.25) 22%, #000 48%);
  mask-image: linear-gradient(90deg, transparent, rgba(0,0,0,.25) 22%, #000 48%);}
.vt-hero .chart .line {stroke-dasharray: 1600; stroke-dashoffset: 1600; animation: vt-trace 2.8s var(--vt-ease) .3s forwards;}
.vt-hero .chart .area {opacity: 0; animation: vt-fade-in 1.4s var(--vt-ease) 1.6s forwards;}
.vt-hero .chart .dot {opacity: 0; animation: vt-fade-in .4s ease 2.9s forwards;}
.vt-hero .chart .halo {opacity: 0; transform-origin: center; transform-box: fill-box;
  animation: vt-halo 2.4s ease-out 3.1s infinite;}
.vt-hero .chart .fvl {opacity: 0; animation: vt-fade-in .8s ease 2.4s forwards;}
@keyframes vt-trace {to {stroke-dashoffset: 0;}}
@keyframes vt-fade-in {to {opacity: 1;}}
@keyframes vt-halo {0% {opacity: .7; transform: scale(1);} 100% {opacity: 0; transform: scale(3.2);}}
.vt-hero .copy {position: relative; max-width: 560px;}
.vt-hero .src {position: absolute; right: 1.2rem; top: 1rem; font-family: var(--vt-mono); font-size: .7rem;
  color: var(--vt-faint); opacity: 0; animation: vt-fade-in .8s ease 2.6s forwards;}
.vt-hero .src span {color: var(--vt-accent);}
.vt-hero h1 {font-family: var(--vt-display) !important; font-stretch: 122%; font-size: 3.1rem !important; line-height: 1.02;
  margin: 1.1rem 0 .8rem !important; letter-spacing: -0.035em; font-weight: 800 !important; padding: 0 !important;}
.vt-hero h1 em {font-style: normal; color: var(--vt-accent);}
.vt-hero p {color: var(--vt-muted); font-size: 1.02rem; margin: 0; max-width: 46ch; line-height: 1.6;}
.vt-hero .facts {display: flex; gap: 1.8rem; margin-top: 1.6rem; flex-wrap: wrap;}
.vt-hero .facts div {font-size: .78rem; color: var(--vt-faint);}
.vt-hero .facts b {display: block; font-family: var(--vt-mono); font-size: 1.15rem; color: var(--vt-text); font-weight: 600;}
.vt-tape {position: relative; overflow: hidden; border-top: 1px solid var(--vt-border); border-bottom: 1px solid var(--vt-border);
  margin: 0 0 1.4rem; padding: .6rem 0; -webkit-mask-image: linear-gradient(90deg, transparent, #000 8%, #000 92%, transparent);
  mask-image: linear-gradient(90deg, transparent, #000 8%, #000 92%, transparent);}
.vt-tape .run {display: flex; gap: 2.6rem; width: max-content; animation: vt-tape 40s linear infinite;}
.vt-tape:hover .run {animation-play-state: paused;}
@keyframes vt-tape {to {transform: translateX(-50%);}}
.vt-tape span {font-family: var(--vt-mono); font-size: .8rem; color: var(--vt-muted); white-space: nowrap;}
.vt-tape span b {color: var(--vt-text); font-weight: 600; margin-right: .5rem;}
.vt-login {text-align: center; margin: 5vh 0 1.6rem;}
.vt-overview {max-width: 1100px; margin: 3.5rem auto 2rem;}
.vt-overview h2 {margin-bottom: .2rem !important;}
.vt-login h1 {font-size: 2rem !important; margin: .9rem 0 .25rem;}
.vt-login p {max-width: 34rem; margin: 0 auto !important;}
.vt-rc {padding: .1rem .1rem .2rem;}
.vt-rc .top {display: flex; justify-content: space-between; align-items: baseline;}
.vt-rc .t {font-family: var(--vt-display); font-stretch: 120%; font-weight: 800; font-size: 1.35rem; letter-spacing: -.02em;}
.vt-rc .d {font-size: .75rem; color: var(--vt-faint); font-family: var(--vt-mono);}
.vt-rc .h {font-size: .86rem; margin-top: .5rem; color: var(--vt-muted);}
.vt-rc .h b {color: var(--vt-text); font-weight: 600;}
[class*="st-key-card_"] {transition: transform .35s var(--vt-ease), border-color .35s var(--vt-ease),
  box-shadow .35s var(--vt-ease), background .35s var(--vt-ease); background: var(--vt-surface); border-radius: 14px;}
[class*="st-key-card_"]:hover {transform: translateY(-3px); border-color: rgba(255,122,26,.5) !important;
  box-shadow: 0 18px 40px -22px rgba(255,122,26,.45); background: #17130f;}
.vt-kpis.two {grid-template-columns: repeat(2, minmax(0, 1fr));}
.vt-kpis.two .vt-kpi:nth-child(odd) {border-left: none; padding-left: 0;}
.vt-kpis.two .vt-kpi:nth-child(n+3) {border-top: 1px solid var(--vt-border);}

/* --- track record ----------------------------------------------------------------------------------------------- */
.vt-dist {display: flex; height: 40px; border-radius: 10px; overflow: hidden; border: 1px solid var(--vt-border);
  margin: .4rem 0 .5rem; gap: 2px; background: var(--vt-border);}
.vt-dist div {display: flex; align-items: center; justify-content: center; font-size: .78rem; font-weight: 650; color: #120a04;
  white-space: nowrap; overflow: hidden; transform-origin: left; animation: vt-grow .9s var(--vt-ease) both; min-width: 0;}
.vt-call {display: flex; flex-direction: column; gap: .6rem;}
.vt-call .hd {display: flex; justify-content: space-between; align-items: flex-start; gap: .6rem;}
.vt-call .tk {font-family: var(--vt-display); font-stretch: 120%; font-weight: 800; font-size: 1.5rem; line-height: 1;
  letter-spacing: -.02em;}
.vt-call .nm {font-size: .76rem; color: var(--vt-faint); margin-top: .35rem; font-family: var(--vt-mono);}
.vt-pill {font-size: .8rem; font-weight: 700; border-radius: 999px; padding: .26rem .75rem; white-space: nowrap; border: 1px solid;}
.vt-call .vd {font-size: .88rem; color: var(--vt-muted);}
.vt-call .vd b {font-weight: 600;}
.vt-call .why {list-style: none; padding: 0; margin: 0; display: grid; gap: .45rem;}
.vt-call .why li {position: relative; padding-left: 1.1rem; font-size: .85rem; line-height: 1.5; color: #ddd3c1; margin: 0;}
.vt-call .why li::before {content: ''; position: absolute; left: 0; top: .55rem; width: 6px; height: 6px; border-radius: 2px;
  background: var(--vt-accent); transform: rotate(45deg);}
.vt-call .ft {display: flex; gap: 1.1rem; flex-wrap: wrap; font-size: .74rem; color: var(--vt-faint);
  border-top: 1px solid var(--vt-border); padding-top: .55rem; font-family: var(--vt-mono);}
.vt-call .ft b {color: var(--vt-muted); font-weight: 500;}
.vt-mini {position: relative; height: 34px; margin: .3rem .2rem 0;}
.vt-mini .tr {position: absolute; top: 22px; left: 0; right: 0; height: 2px; background: #2e2722;}
.vt-mini .gap {position: absolute; top: 19px; height: 8px; border-radius: 4px; transform-origin: left;
  animation: vt-grow .9s var(--vt-ease) .2s both;}
.vt-mini .m {position: absolute; top: 14px; width: 2px; height: 18px; transform: translateX(-1px);}
.vt-mini .lb {position: absolute; top: -1px; font-family: var(--vt-mono); font-size: .68rem; white-space: nowrap;}
.vt-mini .lb.l {transform: translateX(calc(-100% - 4px));} .vt-mini .lb.r {transform: translateX(4px);}

/* --- how it works ----------------------------------------------------------------------------------------------- */
.vt-steps {display: grid; margin: 1rem 0 2rem;}
@media (min-width: 1000px) {.vt-steps {grid-template-columns: repeat(2, minmax(0, 1fr)); grid-template-rows: repeat(4, auto); grid-auto-flow: column; column-gap: 3rem;} .vt-step:nth-child(4)::before {display: none;}}
.vt-step {display: grid; grid-template-columns: 3.2rem minmax(0, 1fr); gap: 1.1rem; position: relative; padding-bottom: 1.6rem;
  animation: vt-in .7s var(--vt-ease) both;}
.vt-step:not(:last-child)::before {content: ''; position: absolute; left: 1.6rem; top: 3.2rem; bottom: 0; width: 1px;
  background: linear-gradient(180deg, rgba(255,122,26,.6), var(--vt-border)); transform-origin: top;
  animation: vt-grow-y 1s var(--vt-ease) both; animation-delay: inherit;}
@keyframes vt-grow-y {from {transform: scaleY(0);}}
.vt-step .n {width: 3.2rem; height: 3.2rem; border-radius: 14px; display: grid; place-items: center; font-family: var(--vt-mono);
  font-weight: 600; color: var(--vt-accent); border: 1px solid rgba(255,122,26,.45); background: var(--vt-accent-dim);}
.vt-step h6 {font-family: var(--vt-display); font-stretch: 112%; font-size: 1.1rem; font-weight: 750; margin: .25rem 0 .3rem;
  color: var(--vt-text); padding: 0;}
.vt-step p {margin: 0; color: var(--vt-muted); font-size: .92rem; line-height: 1.6; max-width: 70ch;}
.vt-step .k {display: flex; gap: .4rem; flex-wrap: wrap; margin-top: .55rem;}
.vt-rules {display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: .9rem 2rem; margin: .5rem 0 1rem;}
.vt-rules div {font-size: .88rem; color: var(--vt-muted); line-height: 1.55; padding-left: 1.6rem; position: relative;}
.vt-rules div svg {position: absolute; left: 0; top: .2rem; color: var(--vt-accent);}
.vt-rules div b {color: var(--vt-text); font-weight: 600; display: block;}

@media (max-width: 900px) {
  .vt-kpis {grid-template-columns: repeat(2, minmax(0, 1fr));}
  .vt-kpi + .vt-kpi {border-left: none; padding-left: 0;} .vt-kpi:nth-child(even) {padding-left: 1rem;}
  .vt-why, .vt-duel, .vt-rules {grid-template-columns: 1fr;}
  .vt-flow {grid-template-columns: repeat(2, minmax(0, 1fr));}
  .vt-hero {padding: 1.8rem 1.3rem;} .vt-hero h1 {font-size: 2.2rem !important;} .vt-hero svg.chart {width: 100%; height: 60%; opacity: .16;} .vt-hero .src {display: none;}
  .vt-ticker {font-size: 2rem;}
  .vt-run .scope .pct {font-size: 2.6rem;}
}
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {animation-duration: .001s !important; animation-iteration-count: 1 !important;
    animation-delay: 0s !important; transition-duration: .001s !important;}
}
</style>
"""


def esc(x) -> str:
    return html.escape(str(x), quote=True)


def chip(level: str, text: str, title: str = "") -> str:
    return (f"<span class='vt-chip {level}' title='{esc(title)}'>{esc(FLAG_LABEL.get(level, level))} · "
            f"{esc(text)}</span>")


def guide(text: str, label: str = "How to read this") -> str:
    """A reading aid next to the thing it explains: what it shows, why the number is what it is, where it comes
    from. Plain text (escaped)."""
    return f"<div class='vt-guide'><b>{esc(label)}</b><span>{esc(text)}</span></div>"


def note(text: str) -> str:
    """A quiet notice for expected gaps (a desk that did not run, data the plan does not cover)."""
    return f"<div class='vt-note'>{esc(text)}</div>"


def dot(colour: str) -> str:
    return f"<span class='vt-dot' style='background:{colour}'></span>"


def count(text: str) -> str:
    """A figure that counts up from zero. `text` is the formatted figure ("$512.30", "+12.4%"); figures with a
    thousands separator or no decimal part are shown as they are (CSS counters cannot group digits)."""
    m = re.fullmatch(r"([^\d]*)(\d+)\.(\d{1,2})([^\d]*)", text or "")
    if not m or "," in text:
        return esc(text)
    pre, i, f, post = m.groups()
    cls = "vt-n d1" if len(f) == 1 else "vt-n"
    return (f"<span class='{cls}' role='img' aria-label='{esc(text)}' data-pre='{esc(pre)}' "
            f"data-post='{esc(post)}' style='--ti:{int(i)};--tf:{int(f)}'></span>")


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
    """Shared chart styling: transparent background, the app's fonts, a quiet warm grid."""
    axis = dict(gridcolor="#221d18", zerolinecolor=BORDER, linecolor=BORDER, tickfont=dict(family=MONO, size=11, color=MUTED),
                title=dict(font=dict(size=12, color=MUTED)))
    base = dict(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font=dict(family=FONT, size=12, color=TEXT),
                xaxis=dict(axis), yaxis=dict(axis, tickfont=dict(family=FONT, size=12, color=TEXT)),
                hoverlabel=dict(bgcolor=SURFACE_2, bordercolor=ACCENT, font=dict(family=FONT, size=12, color=TEXT)),
                margin=dict(l=10, r=10, t=30, b=10), showlegend=False)
    for k, v in kw.items():
        base[k] = {**base[k], **v} if isinstance(v, dict) and isinstance(base.get(k), dict) else v
    return base
