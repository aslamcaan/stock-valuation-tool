"""Earnings preview data (no AI): the next results date and session, consensus, the last eight price reactions, and the
figures to watch. Opens only within 14 days of the results; outside that it says when the preview will open."""
from __future__ import annotations

from datetime import date, timedelta

from engine.earnings import key_numbers, last_moves, move_summary, within_window

SESSION = {"amc": "after the US market close", "bmo": "before the US market opens", "dmh": "during market hours"}


def build_preview(rep, svc, today: date | None = None) -> dict:
    today = today or date.today()
    ne = getattr(getattr(rep.company, "market", None), "next_earnings", None)
    out = {"ticker": rep.ticker, "today": today.isoformat(), "next": ne, "days": None, "notes": []}
    if not ne or not ne.get("date"):
        out["notes"].append("No earnings calendar entry was found, so there is no next results date.")
        return out
    days = within_window(ne["date"], today)
    out["days"] = (date.fromisoformat(ne["date"]) - today).days
    if out["days"] < 0:
        out["notes"].append(f"The results date on this saved report ({ne['date']}) has passed. Re-run the report to get the "
                            "next date.")
        return out
    if days is None:
        out["notes"].append(f"Results are {out['days']} days away; the preview opens 14 days before.")
        return out
    # the calendar and price history (cached by the data layer, so a repeat costs nothing)
    timings: dict[str, str] = {}
    try:
        cal = svc.market.finnhub.call("earnings_calendar", rep.ticker,
                                      **{"from": (today - timedelta(days=3 * 365)).isoformat(),
                                         "to": (today + timedelta(days=30)).isoformat()}).payload
        timings = {r["date"][:10]: r.get("hour") for r in (cal or {}).get("earningsCalendar", []) if r.get("hour")}
    except Exception as exc:  # noqa: BLE001
        out["notes"].append(f"Report timing (before or after the close) is unavailable: {type(exc).__name__}.")
    history: list[dict] = []
    try:
        history = svc.market.fmp.call("earnings", rep.ticker).payload or []
    except Exception as exc:  # noqa: BLE001
        out["notes"].append(f"Earnings history unavailable: {type(exc).__name__}.")
    row = next((r for r in history if r.get("date", "")[:10] == ne["date"][:10]), {})
    out["session"] = SESSION.get(timings.get(ne["date"][:10]))
    out["consensus"] = {"eps": row.get("epsEstimated", ne.get("eps_estimate")), "revenue": row.get("revenueEstimated")}
    res = svc.market.price_history(rep.ticker, (today - timedelta(days=3 * 365)).isoformat())
    closes = res.data if res.available else []
    if not closes:
        out["notes"].append("No price history, so the past moves cannot be computed.")
    next_hour = timings.get(ne["date"][:10])
    out["moves"] = last_moves(history, timings, closes, 8, today, assume_timing=next_hour) if closes else []
    out["summary"] = move_summary(out["moves"])
    out["watch"] = key_numbers(getattr(getattr(rep, "research", None), "data", None))
    out["guidance"] = (getattr(getattr(rep, "research", None), "data", None) or {}).get("guidance", [])
    news = getattr(rep, "news", None)
    out["release"] = next(({"headline": i.headline, "date": i.published, "url": i.url}
                           for i in (news.items if news else []) if i.earnings_release), None)
    out["options_implied_move"] = None
    if any("(assumed)" in m["basis"] for m in out["moves"]):
        out["notes"].append("Where the calendar did not give the session of a past report, it is assumed to be the same "
                            "as the next report's (marked assumed).")
    out["notes"].append("Options-implied move: not available (no options data source is connected). The typical move "
                        "shown is the average of the last eight reactions, not a market forecast.")
    return out
