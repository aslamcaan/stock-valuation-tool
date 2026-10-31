"""The analysis screen shown while a report runs: a scope (an abstract signal until the data desk lands, then the
company's own revenue history), a progress meter, and one node per desk.

The panel is re-rendered every 0.4s. Streamlit keeps the same DOM elements and only patches what changed, so the
animations carry no per-render timing (changing an animation's delay on a live element makes it jump). The
percentage moves continuously: each running desk advances along an easing curve towards its typical duration.
"""
from __future__ import annotations

import math
import time

from ui.theme import ICON, esc

WAITING, RUNNING, DONE, FAILED, SKIPPED = "waiting", "running", "done", "failed", "skipped"

DESK_INFO = {
    "Data desk": "Pulling up to ten years of XBRL facts from SEC EDGAR, normalising units and currency, and "
                 "cross-checking revenue, net income, cash, debt and shares against FMP.",
    "Data checks": "Does the balance sheet balance? Do the statement lines sum to their totals, and does the cash flow "
                   "tie to the change in cash? Is the latest filing fresh?",
    "Research desk": "Reading the latest annual report for segments, geographic mix, one-off items, convertible debt "
                     "and operating KPIs. Every quote is verified against the filing text.",
    "News desk": "Searching company, industry and macro news, then dropping anything stale, undated or unverifiable.",
    "Modelling desk": "Classifying the company's stage, then building the forecast, WACC, DCF, scenarios, peer and "
                      "historical multiples and the blended fair value. All of the arithmetic is Python, not AI.",
    "Review desk": "An independent reviewer challenges each assumption and writes the strongest bull and bear cases.",
    "Impact analyst": "Sizing each material news item's effect on fair value and checking whether the market has "
                      "already priced it in.",
    "MD": "Scoring the rubric, deciding the rating and conviction, and signing off the investment view. Every number "
          "it quotes is checked against the model.",
}


# Typical seconds per desk (weights for the progress meter; a desk that runs long simply approaches its share).
TYPICAL = {"Data desk": 25, "Data checks": 3, "Research desk": 90, "News desk": 90, "Modelling desk": 30,
           "Review desk": 60, "Impact analyst": 45, "MD": 60}


def progress(status: dict, marks: dict, now: float) -> float:
    """Share of the expected work done: finished desks count in full, a running desk by 1 - e^(-t/typical) (capped
    at 95% of its share), so the meter keeps moving while a long desk works."""
    total = sum(TYPICAL.get(d, 30) for d in status)
    done = 0.0
    for d, (state, _) in status.items():
        w = TYPICAL.get(d, 30)
        if state in (DONE, FAILED, SKIPPED):
            done += w
        elif state == RUNNING:
            done += w * min(0.95, 1 - math.exp(-(now - marks[d][1]) / w))
    return min(done / total, 1.0 if all(s in (DONE, FAILED, SKIPPED) for s, _ in status.values()) else 0.99)


def _wave() -> str:
    """An abstract signal (not data) drawn under the scan beam before the company's figures arrive."""
    paths = []
    for k, (amp, freq, op) in enumerate(((26, 1.0, .9), (16, 1.7, .35), (34, .6, .2))):
        pts = []
        for i in range(0, 101):
            x = i * 10
            y = 100 + amp * math.sin(i / 100 * 6.283 * freq * 2 + k)
            pts.append(f"{x},{y:.1f}")
        paths.append(f"<polyline points='{' '.join(pts)}' fill='none' stroke='#ff7a1a' stroke-width='{2 if k == 0 else 1.2}'"
                     f" stroke-opacity='{op}' class='{'line' if k == 0 else ''}'/>")
    return ("<svg viewBox='0 0 1000 200' preserveAspectRatio='none' aria-hidden='true'>" + "".join(paths) + "</svg>")


def _revenue(cd) -> str:
    """The company's reported revenue by fiscal year (from the data desk), rising in once."""
    h = cd.historicals
    pts = [(fy, h.v("revenue", fy)) for fy in h.fy_labels]
    pts = [(fy, v) for fy, v in pts if v is not None and v > 0][-10:]
    if len(pts) < 2:
        return ""
    top = max(v for _, v in pts)
    n, w = len(pts), 800 / len(pts)
    bars = []
    for i, (fy, v) in enumerate(pts):
        bh = v / top * 110
        last = i == n - 1
        bars.append(f"<rect x='{i * w + w * .22:.1f}' y='{135 - bh:.1f}' width='{w * .56:.1f}' height='{bh:.1f}' rx='3' "
                    f"fill='{'#ff7a1a' if last else 'rgba(255,122,26,.32)'}' style='transform-origin:center 135px;"
                    f"transform-box:view-box;animation:vt-grow-y .9s cubic-bezier(.16,1,.3,1) both;"
                    f"animation-delay:{i * .08:.2f}s'/>"
                    f"<text x='{i * w + w / 2:.1f}' y='154' text-anchor='middle' fill='#857b6e' font-size='12' "
                    f"font-family='IBM Plex Mono, monospace'>{esc(fy)}</text>")
    return ("<svg class='bars' viewBox='0 0 800 160' preserveAspectRatio='xMidYMax meet' "
            "aria-label='Reported revenue by fiscal year'>"
            + "".join(bars) + "</svg>")


def panel(run: dict, rep, cost: float) -> str:
    now = time.time()
    status, marks = run["status"], run.setdefault("marks", {})
    for d, (state, _) in status.items():  # when each desk entered its current state
        if marks.get(d, (None,))[0] != state:
            marks[d] = (state, now)
    finished = sum(1 for s, _ in status.values() if s in (DONE, FAILED, SKIPPED))
    running = [d for d, (s, _) in status.items() if s == RUNNING]
    pct = progress(status, marks, now)
    elapsed = now - run["started"]

    cd = getattr(rep, "company", None) if rep is not None else None
    if cd is not None:
        scope = _revenue(cd) or _wave()
        h = cd.historicals
        caption = f"{esc(cd.profile.name)} · reported revenue, {esc(h.currency)}"
    else:
        scope, caption = _wave(), "Fetching filings and market data"

    nodes = []
    for d, (state, msg) in status.items():
        icon = {DONE: ICON["check"], FAILED: ICON["cross"], SKIPPED: ICON["dash"]}.get(state, "")
        pop = " style='animation:vt-pop .5s cubic-bezier(.16,1,.3,1) both'" if state == DONE else ""
        nodes.append(f"<div class='vt-node {state}'><div class='hd'><span class='ic'{pop}>{icon}</span>"
                     f"<span class='nm'>{esc(d)}</span></div><div class='ms' title='{esc(msg)}'>"
                     f"{esc(msg if state != WAITING else 'Waiting')}</div></div>")

    lead = running[0] if running else None
    now_line = (f"<div class='now'><span class='who'>{esc(lead)}</span><span class='what'>{esc(status[lead][1])}</span>"
                f"</div><div class='about'>{esc(DESK_INFO.get(lead, ''))}</div>") if lead else \
        "<div class='now'><span class='who'>Finishing</span><span class='what'>Saving the report…</span></div>"
    return (f"<div class='vt-run'><div class='scope'>{scope}<div class='beam'></div>"
            f"<div class='meta'><div><div class='tk'>{caption}</div>"
            f"<div class='pct'>{pct * 100:.0f}<small>%</small></div></div></div>"
            f"<div class='clock'><b>{elapsed // 60:.0f}m {elapsed % 60:02.0f}s</b> elapsed<br>"
            f"{finished} of {len(status)} desks done<br>AI cost <b>${cost:.3f}</b></div></div>"
            f"<div class='bar'><i style='width:{pct * 100:.1f}%'></i></div>{now_line}"
            f"<div class='vt-flow'>{''.join(nodes)}</div></div>")


def desk_nodes(status: dict) -> str:
    """The desks of a finished report, as the same nodes the analysis screen shows (for the Desk log tab)."""
    icons = {DONE: ICON["check"], FAILED: ICON["cross"], SKIPPED: ICON["dash"]}
    return "<div class='vt-flow' style='padding:0'>" + "".join(
        f"<div class='vt-node {state}'><div class='hd'><span class='ic'>{icons.get(state, '')}</span>"
        f"<span class='nm'>{esc(d)}</span></div><div class='ms' style='height:auto;-webkit-line-clamp:4'>{esc(msg)}"
        f"</div></div>" for d, (state, msg) in status.items()) + "</div>"
