"""Runs the desks for one stock and streams status updates (for the progress panel).

Order and dependencies:
  Data desk -> Data checks (hard stops end the run) -> [Research desk || peer gathering] -> Modelling desk
  -> Review desk (may re-run modelling with a stage override) -> MD -> saved report.
Status events go through a queue because Streamlit can only update the UI from the main thread.
"""
from __future__ import annotations

import queue
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeout
from dataclasses import dataclass, field
from datetime import date, datetime, timezone

from core.config import PROJECT_ROOT
from data_desk.builder import CompanyData, DataDeskError, build_company_data
from data_desk.exposure import ExposureProfile, build_exposure
from data_desk.filings import latest_annual_report
from data_desk.peers import gather_peers
from core.cache import CacheMiss
from core.http import DataSourceError
from desks.ai import AIError, CostCapExceeded
from desks.md import MDResult, run_md
from desks.modelling import ValuationReport, run_modelling
from desks.news import NewsResult, run_news
from desks.research import ResearchResult, run_research
from desks.review import STAGES, run_review
from desks.summary import build_summary
from engine.valuation import ValuationError

DESKS = ["Data desk", "Data checks", "Research desk", "News desk", "Modelling desk", "Review desk", "MD"]
WAITING, RUNNING, DONE, FAILED, SKIPPED = "waiting", "running", "done", "failed", "skipped"
REPORTS_DIR = PROJECT_ROOT / "data" / "reports"


@dataclass
class Event:
    desk: str
    state: str
    message: str
    at: float = field(default_factory=time.time)
    cost: float | None = None


@dataclass
class FullReport:
    report_id: str
    ticker: str
    created_at: str
    valuation_date: date
    company: CompanyData | None = None
    model: ValuationReport | None = None
    research: ResearchResult | None = None
    review: dict | None = None
    md: MDResult | None = None
    guard_log: list[str] = field(default_factory=list)
    stopped: str | None = None            # plain-English reason the run stopped early
    ai_cost: float = 0.0
    desk_status: dict[str, tuple[str, str]] = field(default_factory=dict)
    save_error: str | None = None
    exposure: ExposureProfile | None = None
    news: NewsResult | None = None
    overrides: dict = field(default_factory=dict)
    peers_pool: list = field(default_factory=list)   # all peer candidates (reused when assumptions are edited)
    peer_notes: list[str] = field(default_factory=list)


class Progress:
    def __init__(self, q: queue.Queue | None = None):
        self.q = q
        self.status: dict[str, tuple[str, str]] = {d: (WAITING, "Waiting") for d in DESKS}
        self._lock = threading.Lock()

    def __call__(self, desk: str, state: str, message: str, cost: float | None = None) -> None:
        with self._lock:
            self.status[desk] = (state, message)
        if self.q is not None:
            self.q.put(Event(desk, state, message, cost=cost))


def _sources_text(research: ResearchResult | None, filing) -> str:
    return "\n".join(filing.sections.values()) if filing else ""


def run_report(ticker: str, svc, events: queue.Queue | None = None, valuation_date: date | None = None,
               overrides: dict | None = None, use_ai: bool = True, holder: dict | None = None) -> FullReport:
    """`holder['report']` exposes the report while it is being built, so the UI can render finished sections."""
    today = valuation_date or date.today()
    rid = f"{ticker.upper()}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}-{uuid.uuid4().hex[:6]}"
    rep = FullReport(rid, ticker.upper(), datetime.now(timezone.utc).isoformat(timespec="seconds"), today,
                     overrides=dict(overrides or {}))
    if holder is not None:
        holder["report"] = rep
    p = Progress(events)

    def cost():
        return svc.ai.report_cost(rid)

    # --- data desk ------------------------------------------------------------------------------------------------
    p("Data desk", RUNNING, "Fetching filings, prices and market data…")
    try:
        cd = build_company_data(ticker, svc, today=today, progress=lambda m: p("Data desk", RUNNING, m))
    except DataDeskError as exc:
        p("Data desk", FAILED, str(exc))
        rep.stopped = str(exc)
        return _finish(rep, p, cost(), svc.store)
    rep.company = cd
    h = cd.historicals
    p("Data desk", DONE, f"Fetched {len(h.fy_labels)} annual periods{' + ' + h.ltm.label if h.ltm else ''}, "
                         f"price {cd.market.price.source if cd.market.price else 'unavailable'}")

    # --- data checks -----------------------------------------------------------------------------------------------
    p("Data checks", RUNNING, "Checking the balance sheet, cash flow and market cap…")
    if cd.hard_stops:
        msg = " ".join(f"{f.title}: {f.message}" for f in cd.hard_stops)
        p("Data checks", FAILED, msg)
        rep.stopped = f"Valuation refused because a hard check failed. {msg}"
        return _finish(rep, p, cost(), svc.store)
    reds = sum(1 for f in cd.flags if f.level == "red")
    ambers = sum(1 for f in cd.flags if f.level == "amber")
    p("Data checks", DONE, f"No hard stops · {reds} red · {ambers} amber flags")

    # --- research desk || peers ---------------------------------------------------------------------------------------
    filing = None

    def research_job():
        nonlocal filing
        if not use_ai:
            p("Research desk", SKIPPED, "AI desks switched off")
            return None
        p("Research desk", RUNNING, "Reading the annual report: business, segments, risk factors, MD&A…")
        filing = latest_annual_report(svc, cd.profile.cik)
        if filing is None:
            p("Research desk", FAILED, "No annual report found on EDGAR")
            return None
        r = run_research(svc.ai, rid, cd.profile.name, cd.profile.ticker, filing)
        p("Research desk", DONE, f"Read {filing.form} filed {filing.filing_date}: {len(r.data.get('segments', []))} "
                                 f"segments, {len(r.data.get('risk_factors', []))} risks, "
                                 f"{len(r.data.get('one_off_items', []))} one-off items"
                                 + (f" ({len(r.dropped)} unverified items dropped)" if r.dropped else ""), cost())
        return r

    def peers_job():
        p("Modelling desk", RUNNING, "Gathering comparable companies…")
        return gather_peers(svc, cd.profile.ticker, progress=lambda m: p("Modelling desk", RUNNING, m))

    with ThreadPoolExecutor(max_workers=2) as pool:
        f_res, f_peers = pool.submit(research_job), pool.submit(peers_job)
        try:
            research = f_res.result()
        except CostCapExceeded as exc:
            p("Research desk", FAILED, str(exc))
            research, use_ai = None, False
            rep.stopped = str(exc)
        except AIError as exc:
            p("Research desk", FAILED, str(exc))
            research = None
        peers, peer_notes = f_peers.result()
    rep.research = research
    rep.peers_pool, rep.peer_notes = peers, peer_notes
    try:
        rep.exposure = build_exposure(cd, research)
    except Exception as exc:  # the exposure profile only feeds the news desk; it must not break the valuation
        rep.exposure = ExposureProfile(notes=[f"The exposure profile could not be built: {type(exc).__name__}: {exc}"])
    news_pool = ThreadPoolExecutor(max_workers=1)
    news_future = news_pool.submit(_news_job, svc, rid, cd, rep.exposure, peers, p, use_ai, cost, rep.stopped)

    def value_review_and_md() -> None:
        # --- modelling desk ---
        p("Modelling desk", RUNNING, "Building the forecast, WACC, DCF, comps and verdict…")
        try:
            model = run_modelling(cd, svc, today, rep.overrides, progress=lambda m: p("Modelling desk", RUNNING, m),
                                  peers=peers, research=research.data if research else None)
        except ValuationError as exc:
            p("Modelling desk", FAILED, str(exc))
            rep.stopped = str(exc)
            return
        model.notes += peer_notes
        rep.model = model
        vd = model.verdict
        p("Modelling desk", DONE, f"{model.valuation.classification.stage_label}; fair value "
                                  f"{'n/a' if vd.fair_value is None else f'${vd.fair_value:,.2f}'} → {vd.verdict}")
        if not use_ai:
            for d in ("Review desk", "MD"):
                p(d, SKIPPED, "AI desks switched off" if not rep.stopped else "Stopped: AI cost cap reached")
            log_to_track_record(rep, svc.store)
            return

        sources = _sources_text(research, filing)
        research_view = _research_for_ai(research)
        # --- review desk ---
        try:
            p("Review desk", RUNNING, "Challenging assumptions and writing the bear case…")
            review, log = run_review(svc.ai, rid, build_summary(model, research_view), sources)
            rep.guard_log += log
            sr = review.get("stage_review", {})
            if not sr.get("agree", True) and sr.get("suggested_stage") in STAGES and \
                    sr["suggested_stage"] != model.valuation.classification.stage and "stage" not in rep.overrides:
                rep.overrides.update(stage=sr["suggested_stage"], stage_reason=f"Review desk: {sr.get('reason', '')}")
                p("Review desk", RUNNING, f"Stage overridden to {sr['suggested_stage']}: re-running the model…")
                model = run_modelling(cd, svc, today, rep.overrides, peers=peers,
                                      research=research.data if research else None)
                model.notes += peer_notes
                rep.model = model
            rep.review = review
            p("Review desk", DONE, f"{len(review.get('challenges', []))} challenges; bear case written", cost())

            p("MD", RUNNING, "Scoring the rubric and writing the investment view…")
            md = run_md(svc.ai, rid, model, build_summary(model, research_view), review, sources)
            rep.md = md
            rep.guard_log += md.guard_log
            p("MD", DONE, f"{md.rating} (conviction {md.conviction})", cost())
            log_to_track_record(rep, svc.store)
        except CostCapExceeded as exc:
            rep.stopped = str(exc)
            for d in ("Review desk", "MD"):
                if p.status[d][0] in (WAITING, RUNNING):
                    p(d, FAILED, str(exc))
        except AIError as exc:
            for d in ("Review desk", "MD"):
                if p.status[d][0] in (WAITING, RUNNING):
                    p(d, FAILED, str(exc))

    try:
        value_review_and_md()
    finally:  # whatever happens above, the news thread is joined (with a time limit) before the report is saved
        rep.news = _collect(news_future, news_pool, p)
    return _finish(rep, p, cost(), svc.store)


NEWS_TIMEOUT = 180  # seconds to wait for the news desk after the MD finishes


def _news_job(svc, rid, cd, exposure, peers, p, use_ai, cost, stopped=None) -> NewsResult | None:
    if not use_ai:
        p("News desk", SKIPPED, "Stopped: AI cost cap reached" if stopped else "AI desks switched off")
        return None
    p("News desk", RUNNING, "Searching macro, industry and company news: " + "; ".join(exposure.search_topics[:3]) + "…")
    try:
        names = [getattr(x, "name", None) or getattr(x, "ticker", "") for x in peers][:6]
        res = run_news(svc.ai, svc, rid, cd, exposure, [n for n in names if n])
    except CostCapExceeded as exc:
        p("News desk", FAILED, str(exc))
        return None
    except (AIError, DataSourceError, CacheMiss) as exc:
        p("News desk", FAILED, f"{type(exc).__name__}: {exc}")
        return None
    except Exception as exc:  # never leave the desk showing "running"; the report carries on without news
        p("News desk", FAILED, f"Unexpected error: {type(exc).__name__}: {exc}")
        raise
    counts = ", ".join(f"{len(res.tier(t))} {t}" for t in ("macro", "micro", "industry", "company"))
    p("News desk", DONE, f"{counts} items" + (f" ({len(res.dropped)} dropped: unverified date, too old or "
                                              f"off-profile)" if res.dropped else ""), cost())
    return res


def _collect(future, pool, p) -> NewsResult | None:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    try:
        return future.result(timeout=NEWS_TIMEOUT)
    except FuturesTimeout:
        future.cancel()
        msg = f"timed out after waiting {NEWS_TIMEOUT} seconds"
        p("News desk", FAILED, msg.capitalize())
        return NewsResult(as_of=now, error=msg)
    except Exception as exc:  # the news desk must never break the valuation report
        return NewsResult(as_of=now, error=f"{type(exc).__name__}: {exc}")
    finally:
        pool.shutdown(wait=False)


def _research_for_ai(research: ResearchResult | None) -> dict:
    if not research:
        return {}
    keep = ("business_summary", "segments", "geographic_mix", "kpis", "risk_factors", "one_off_items", "guidance",
            "convertible_debt", "share_classes", "key_customers", "key_suppliers", "regulators")
    return {k: research.data.get(k) for k in keep}


def _finish(rep: FullReport, p: Progress, cost: float, store) -> FullReport:
    rep.ai_cost = cost
    rep.desk_status = dict(p.status)
    try:
        save(rep, store)
    except Exception as exc:  # the report is still shown; it just is not kept
        rep.save_error = f"The report could not be saved ({type(exc).__name__}: {exc})."
    return rep


def log_to_track_record(rep: FullReport, store) -> None:
    """Every completed report (a verdict was reached) goes into the track record."""
    if rep.model is None or rep.model.verdict.fair_value is None:
        return
    from data_desk.sector_etf import sector_etf
    created = datetime.fromisoformat(rep.created_at)
    store.log_call({
        "report_id": rep.report_id, "ticker": rep.ticker, "call_date": created.date().isoformat(),
        "call_time": created.strftime("%H:%M"), "price": rep.model.verdict.price,
        "fair_value": rep.model.verdict.fair_value, "verdict": rep.model.verdict.verdict,
        "rating": rep.md.rating if rep.md else None, "conviction": rep.md.conviction if rep.md else None,
        "confidence": rep.model.verdict.confidence,
        "toolkit": rep.model.valuation.classification.toolkit, "stage": rep.model.valuation.classification.stage,
        "sector_etf": sector_etf(rep.company.profile.sic)})


def headline(rep: FullReport) -> str:
    vd = rep.model.verdict if rep.model else None
    return ((f"{vd.verdict} (fair value ${vd.fair_value:,.2f})" if vd and vd.fair_value else (rep.stopped or "incomplete"))
            + (f" · {rep.md.rating}" if rep.md else ""))


def save(rep: FullReport, store) -> None:
    store.save_report(rep.report_id, rep.ticker, rep.created_at, headline(rep), rep)


def load(report_id: str, store) -> FullReport:
    return store.load_report(report_id)


def import_legacy_files(store) -> int:
    """Reports saved as .pkl files before the database store: copy them in once (local only)."""
    import pickle

    n = 0
    for path in REPORTS_DIR.glob("*/*.pkl") if REPORTS_DIR.exists() else []:
        try:
            with open(path, "rb") as fh:
                rep = pickle.load(fh)
            save(rep, store)
            path.rename(path.with_suffix(".pkl.imported"))
            n += 1
        except Exception:  # an unreadable old file is skipped, not fatal
            continue
    return n
