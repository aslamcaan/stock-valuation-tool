"""Earnings preview (pure). Moves after past results come from daily closes and the results dates; nothing here is an
options-implied move (no free options source is wired in), so the typical move is labelled as the history's own."""
from __future__ import annotations

from datetime import date, timedelta
from statistics import mean, median

WINDOW_DAYS = 14


def _closes(rows: list[dict]) -> list[tuple[str, float]]:
    return sorted((r["date"][:10], float(r["close"])) for r in rows if r.get("close"))


def reaction(day: str, timing: str | None, closes: list[tuple[str, float]]) -> dict | None:
    """The share-price move caused by results on `day`. After the close ('amc') the reaction is the next session's close
    against that day's; before the open or in hours ('bmo', 'dmh') it is that day's close against the previous one. With
    no timing it is the two-session move from the close before `day` to the close after it, and says so."""
    dates = [d for d, _ in closes]
    px = dict(closes)
    before = [d for d in dates if d < day]
    on = day if day in px else None
    after = [d for d in dates if d > day]
    if not before or not after:
        return None
    prev, nxt = before[-1], after[0]
    if timing == "amc" and on:
        a, b, basis = on, nxt, "after the close"
    elif timing in ("bmo", "dmh") and on:
        a, b, basis = prev, on, "before the open" if timing == "bmo" else "in market hours"
    else:
        a, b, basis = prev, nxt, "timing unknown: two-session move"
    return {"date": day, "from": a, "to": b, "move": px[b] / px[a] - 1, "basis": basis}


def last_moves(history: list[dict], timings: dict[str, str], closes_rows: list[dict], n: int = 8,
               today: date | None = None) -> list[dict]:
    """The last `n` reported results (those with an actual EPS), newest first, each with its price reaction and the EPS
    surprise (actual against the consensus estimate, in the provider's figures)."""
    closes = _closes(closes_rows)
    today_s = (today or date.today()).isoformat()
    rows = sorted((r for r in history if r.get("epsActual") is not None and r["date"][:10] < today_s),
                  key=lambda r: r["date"], reverse=True)
    out = []
    for r in rows:
        d = r["date"][:10]
        rx = reaction(d, timings.get(d), closes)
        if rx is None:
            continue
        est, act = r.get("epsEstimated"), r.get("epsActual")
        rx["eps_actual"], rx["eps_estimate"] = act, est
        rx["surprise"] = None if est in (None, 0) else (act - est) / abs(est)
        out.append(rx)
        if len(out) == n:
            break
    return out


def move_summary(moves: list[dict]) -> dict | None:
    if not moves:
        return None
    mags = [abs(m["move"]) for m in moves]
    return {"n": len(moves), "mean_abs": mean(mags), "median_abs": median(mags), "up": sum(1 for m in moves if m["move"] > 0),
            "largest": max(moves, key=lambda m: abs(m["move"]))}


def within_window(next_date: str | None, today: date, days: int = WINDOW_DAYS) -> int | None:
    """Days until results if they fall within the window, else None."""
    if not next_date:
        return None
    d = (date.fromisoformat(next_date[:10]) - today).days
    return d if 0 <= d <= days else None


def key_numbers(research: dict | None, limit: int = 3) -> list[dict]:
    """The few figures to watch, chosen by rule from the annual report's extracts: the volume KPI the company reports, the
    segments by size of revenue, and any guidance metric it states. Each carries its verbatim quote."""
    data = research or {}
    out: list[dict] = []
    vk = (data.get("business") or {}).get("volume_kpi") or {}
    if vk.get("name"):
        out.append({"label": vk["name"], "why": "the volume the company's revenue is earned on", "quote": vk.get("quote", "")})
    segs = sorted(((s.get("revenue_millions") or 0, s) for s in (data.get("business") or {}).get("segments", [])),
                  key=lambda x: -x[0])
    for rev, s in segs[:2]:
        if rev:
            out.append({"label": f"{s['name']} revenue", "why": "the largest segment by revenue",
                        "quote": s.get("quote", "")})
    for g in (data.get("risks") or {}).get("guidance", [])[:1]:
        out.append({"label": f"Guidance: {g.get('metric', '')}", "why": g.get("guidance_text", ""), "quote": g.get("quote", "")})
    return out[:limit]
