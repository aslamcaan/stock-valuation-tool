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

from core.cache import CacheMiss
from core.config import PROJECT_ROOT
from core.http import DataSourceError
from data_desk.builder import CompanyData, DataDeskError, build_company_data
from data_desk.exposure import ExposureProfile, build_exposure
from data_desk.filings import latest_annual_report
from data_desk.ownership import Ownership, build_ownership
from data_desk.peers import gather_peers
from desks.ai import AIError, CostCapExceeded
from desks.guarded import recheck
from desks.impact import ImpactResult, impact_payload, run_impact, run_news_view
from desks.md import MDResult, run_md
from desks.modelling import ValuationReport, run_modelling
from desks.news import NewsResult, run_news
from desks.research import ResearchResult, merge_one_offs, run_one_offs, run_research
from desks.review import STAGES, run_review
from desks.summary import build_summary
from engine.forensic import ForensicScore, forensic_scores
from engine.valuation import ValuationError

DESKS = ["Data desk", "Data checks", "Research desk", "News desk", "Modelling desk", "Review desk", "Impact analyst",
         "MD"]
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
    impact: ImpactResult | None = None
    ownership: Ownership | None = None
    forensic: dict[str, list[ForensicScore]] | None = None
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
    fallbacks_from = len(getattr(svc.cache, "fallbacks", []))  # stale copies served during this run

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
        filing = latest_annual_report(svc, cd.profile.statements_cik)
        if filing is None:
            p("Research desk", FAILED, "No annual report found on EDGAR")
            return None
        r = run_research(svc.ai, rid, cd.profile.name, cd.profile.ticker, filing)
        earlier = []  # one-off items for the years before the latest MD&A's two or three: a 5-year clean margin history
        for back in (2, 4):
            try:
                p("Research desk", RUNNING, f"Reading the annual report from {back} years earlier for one-off items…")
                older = latest_annual_report(svc, cd.profile.statements_cik, years_back=back)
                if older is not None:
                    earlier.append(run_one_offs(svc.ai, rid, cd.profile.name, cd.profile.ticker, older))
            except Exception as exc:  # the latest report's items are still usable
                r.dropped.append(f"annual report from {back} years earlier not read: {type(exc).__name__}: {exc}")
        merge_one_offs(r, earlier, int(filing.report_date[:4]))
        p("Research desk", DONE, f"Read {filing.form} filed {filing.filing_date}: {len(r.data.get('segments', []))} "
                                 f"segments, {len(r.data.get('risk_factors', []))} risks, "
                                 f"{len(r.data.get('one_off_items', []))} one-off items"
                                 + (f" ({len(r.dropped)} unverified items dropped)" if r.dropped else ""), cost())
        return r

    def peers_job():
        p("Modelling desk", RUNNING, "Gathering comparable companies…")
        return gather_peers(svc, cd.profile.ticker, progress=lambda m: p("Modelling desk", RUNNING, m))

    def ownership_job():  # code only (SEC Form 4 and 13D/G, FINRA); never stops the report
        try:
            m = cd.market  # FINRA counts US-listed shares: ordinary shares / ADR ratio
            shares = m.shares.value / (m.adr_ratio or 1) if m.shares and m.shares.value else None
            return build_ownership(svc, cd.profile.cik, cd.profile.ticker, shares, today)
        except Exception as exc:
            return Ownership(as_of=today.isoformat(), notes=[f"Ownership data unavailable: {type(exc).__name__}: "
                                                             f"{exc}"])

    with ThreadPoolExecutor(max_workers=3) as pool:
        f_res, f_peers, f_own = pool.submit(research_job), pool.submit(peers_job), pool.submit(ownership_job)
        try:
            research = f_res.result()
        except CostCapExceeded as exc:
            p("Research desk", FAILED, str(exc))
            research, use_ai = None, False
            rep.stopped = str(exc)
        except Exception as exc:  # AIError, or the filing could not be fetched: the valuation goes on without it
            p("Research desk", FAILED, f"{type(exc).__name__}: {exc}")
            research = None
        try:
            peers, peer_notes = f_peers.result()
        except Exception as exc:
            peers, peer_notes = [], [f"Peers could not be gathered: {type(exc).__name__}: {exc}"]
        rep.ownership = f_own.result()
    rep.research = research
    rep.peers_pool, rep.peer_notes = peers, peer_notes
    try:
        rep.exposure = build_exposure(cd, research)
    except Exception as exc:  # the exposure profile only feeds the news desk; it must not break the valuation
        rep.exposure = ExposureProfile(notes=[f"The exposure profile could not be built: {type(exc).__name__}: {exc}"])
    news_pool = ThreadPoolExecutor(max_workers=1)
    news_future = news_pool.submit(_news_job, svc, rid, cd, rep.exposure, peers, p, use_ai, cost, rep.stopped)

    joined: dict = {}

    def news_now() -> NewsResult | None:  # joins the news thread once
        if "news" not in joined:
            joined["news"] = _collect(news_future, news_pool, p)
        return joined["news"]

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
        model.notes += peer_notes + list(dict.fromkeys(getattr(svc.cache, "fallbacks", [])[fallbacks_from:]))
        rep.model = model
        rep.forensic = _forensic(cd, model)
        vd = model.verdict
        what = model.valuation.classification.stage_label if model.valuation else f"{model.toolkit} toolkit"
        p("Modelling desk", DONE, f"{what}; fair value "
                                  f"{'n/a' if vd.fair_value is None else f'${vd.fair_value:,.2f}'} → {vd.verdict}")
        if not use_ai:
            for d in ("Review desk", "Impact analyst", "MD"):
                p(d, SKIPPED, "AI desks switched off" if not rep.stopped else "Stopped: AI cost cap reached")
            log_to_track_record(rep, svc.store)
            return

        sources = _sources_text(research, filing)
        research_view = _research_for_ai(research)

        def summary_of(m):  # computed results for the AI desks, with ownership and forensic scores
            return {**build_summary(m, research_view), **extras_for_ai(rep)}
        # --- review desk ---
        svc.ai.ledger.hold(rid, MD_HOLD)  # the review and impact desks may not spend the MD's budget
        try:
            p("Review desk", RUNNING, "Challenging assumptions and writing the bear case…")
            try:
                review, log = run_review(svc.ai, rid, summary_of(model), sources)
                review_failed = None
            except (AIError, CostCapExceeded) as exc:  # the MD still signs off (its budget is held), without it
                review, log, review_failed = {}, [], f"{type(exc).__name__}: {exc}"
            rep.guard_log += log
            sr = review.get("stage_review", {})
            if model.valuation is not None and not sr.get("agree", True) and sr.get("suggested_stage") in STAGES \
                    and sr["suggested_stage"] != model.valuation.classification.stage and "stage" not in rep.overrides:
                rep.overrides.update(stage=sr["suggested_stage"], stage_reason=f"Review desk: {sr.get('reason', '')}")
                p("Review desk", RUNNING, f"Stage overridden to {sr['suggested_stage']}: re-running the model…")
                try:
                    model = run_modelling(cd, svc, today, rep.overrides, peers=peers,
                                          research=research.data if research else None)
                except ValuationError as exc:  # the suggested stage cannot be valued: the code's stage stands
                    rep.overrides.pop("stage", None)
                    rep.overrides.pop("stage_reason", None)
                    model.notes.append(f"The review desk suggested the {sr['suggested_stage']} stage, but that "
                                       f"model could not be valued ({exc}); the code's classification stands.")
                else:
                    model.notes += peer_notes
                    rep.model = model
                    rep.forensic = _forensic(cd, model)
                    review, relog = recheck(review, summary_of(model), sources, "Review desk")
                    rep.guard_log += relog
            rep.review = review or None
            if review_failed:
                p("Review desk", FAILED, review_failed)
            else:
                p("Review desk", DONE, f"{len(review.get('challenges', []))} challenges; bear case written", cost())

            rep.news = news_now()
            rep.impact = _impact_job(svc, rid, model, rep.news, rep.exposure, summary_of(model),
                                     sources, p, cost)
            news_view = impact_payload(rep.impact) if rep.impact and not rep.impact.error else None
            if rep.impact:
                rep.guard_log += rep.impact.guard_log

            p("MD", RUNNING, "Scoring the rubric and writing the investment view…")
            svc.ai.ledger.unhold(rid)
            md = run_md(svc.ai, rid, model, summary_of(model), review, sources, news=news_view)
            rep.md = md
            rep.guard_log += md.guard_log
            if rep.impact and rep.impact.items and not rep.impact.error:
                p("MD", RUNNING, "Writing what the news means…")
                n_log = len(rep.impact.guard_log)
                try:
                    run_news_view(svc.ai, rid, rep.impact, md.rating, md.conviction, sources)
                except Exception as exc:  # the news summary is optional: the rating stands without it
                    rep.impact.notes.append(f"The MD's news summary could not be written: {exc}")
                rep.guard_log += rep.impact.guard_log[n_log:]
            p("MD", DONE, f"{md.rating} (conviction {md.conviction})", cost())
            log_to_track_record(rep, svc.store)
        except CostCapExceeded as exc:
            rep.stopped = str(exc)
            for d in ("Review desk", "Impact analyst", "MD"):
                if p.status[d][0] in (WAITING, RUNNING):
                    p(d, FAILED, str(exc))
        except AIError as exc:
            for d in ("Review desk", "Impact analyst", "MD"):
                if p.status[d][0] in (WAITING, RUNNING):
                    p(d, FAILED, str(exc))

    try:
        value_review_and_md()
    finally:  # whatever happens above, the news thread is joined (with a time limit) before the report is saved
        svc.ai.ledger.unhold(rid)  # never leave the MD's set-aside counting against the daily cap
        rep.news = news_now()
        if rep.impact is None and p.status["Impact analyst"][0] == WAITING:
            p("Impact analyst", SKIPPED, "No valuation or AI desks off" if rep.model is None or not use_ai
              else "Not reached")
    return _finish(rep, p, cost(), svc.store)


def _impact_job(svc, rid, model, news, exposure, summary, sources, p, cost) -> ImpactResult | None:
    """The impact analyst never breaks the report: on any failure the MD carries on without the news analysis."""
    if news is None or news.error or not news.items:
        p("Impact analyst", SKIPPED, "No news to analyse" if news is None or not news.error
          else "News desk failed")
        return None
    p("Impact analyst", RUNNING, f"Working through {min(len(news.items), 10)} news items: driver, size, priced in…")
    try:
        res = run_impact(svc.ai, svc, rid, model, news, summary, exposure, sources)
    except CostCapExceeded as exc:  # optional desk: leave the remaining budget to the MD's rating
        p("Impact analyst", FAILED, str(exc))
        return None
    except Exception as exc:
        p("Impact analyst", FAILED, f"{type(exc).__name__}: {exc}")
        return ImpactResult(news.as_of, model.verdict.fair_value, model.verdict.verdict, model.verdict.price,
                            error=f"{type(exc).__name__}: {exc}")
    q = sum(i.quantified for i in res.items)
    adj = res.adjusted_fair_value
    p("Impact analyst", DONE, f"{len(res.items)} items, {q} quantified; news-adjusted fair value "
                              f"{'n/a' if adj is None else f'${adj:,.2f}'}", cost())
    return res


MD_HOLD = 0.15  # US$ set aside for the MD from the review desk on (its worst case at MAX_TOKENS is about $0.14)
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


def _forensic(cd, model) -> dict:
    """Scores on the reporting-currency statements. The original Z's market value of equity is converted from US$
    at the period-end rate the statements were converted at (FRED), read off total assets."""
    try:
        h, hu = cd.historicals, cd.historicals_usd
        mc = model.inputs.market_cap
        mc = getattr(mc, "value", mc)
        src = "computed market cap (price x shares / ADR ratio)"
        if mc is not None and h.currency != "USD":
            last = h.fy_labels[-1]
            local, usd = h.v("total_assets", last), hu.v("total_assets", last) if hu else None
            if local and usd:
                mc, src = mc * local / usd, f"{src}, US$ converted to {h.currency} at the {last} period-end FRED rate"
            else:
                mc, src = None, f"no {h.currency}/US$ rate to convert the market cap"
        return forensic_scores(h, cd.profile.sic, mc, src)
    except Exception as exc:  # a forensic score is a cross-check; it must never stop the valuation
        return {"beneish": [], "altman": [], "piotroski": [], "error": f"{type(exc).__name__}: {exc}"}


def extras_for_ai(rep: FullReport) -> dict:
    """Ownership and forensic figures for the AI desks (all computed by code; rounded as shown in the report)."""
    out: dict = {}
    own = getattr(rep, "ownership", None)
    if own is not None:
        s = own.summary()
        out["insider_activity"] = {"as_of": own.as_of, "window_days": s["window_days"],
                                   "open_market_buys": s["buys"], "open_market_sells": s["sells"],
                                   "buy_value_usd_m": round(s["buy_value"] / 1e6, 2),
                                   "sell_value_usd_m": round(s["sell_value"] / 1e6, 2),
                                   "sells_under_10b5_1_plans": s["planned_sells"], "distinct_buyers": s["buyers"],
                                   "distinct_sellers": s["sellers"], "notes": own.notes}
        out["major_holders"] = [{"name": h.name, "percent": h.percent, "as_of": h.event_date}
                                for h in own.holders[:5]]
        if own.short:
            last = own.short[-1]
            out["short_interest"] = {"settlement_date": last["settlement_date"],
                                     "pct_of_shares": None if last["pct_of_shares"] is None
                                     else round(last["pct_of_shares"], 4),
                                     "days_to_cover": last["days_to_cover"]}
    fs = getattr(rep, "forensic", None)
    if fs:
        b = next((x for x in reversed(fs.get("beneish", [])) if x.value is not None), None)
        a = next((x for x in reversed(fs.get("altman", [])) if x.value is not None), None)
        f_ = next((x for x in reversed(fs.get("piotroski", [])) if x.value is not None), None)

        def view(x):  # notes contain figures as text; they are passed as numbers too, so they can be quoted
            return {"model": x.name, "period": x.period, "score": round(x.value, 2), "reading": x.reading,
                    "notes": x.notes, **getattr(x, "figures", {})}
        out["forensic"] = {"beneish_m": None if b is None else view(b), "altman": None if a is None else view(a),
                           "piotroski_f": None if f_ is None else view(f_)}
    return out


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
        "toolkit": rep.model.toolkit,
        "stage": rep.model.valuation.classification.stage if rep.model.valuation else None,
        "sector_etf": sector_etf(rep.company.profile.sic)})


def refresh_news(rep: FullReport, svc) -> FullReport:
    """Re-run the news desk only (fresh search), then the impact analysis and the MD's news summary, and re-save.
    The base valuation, the rating and the rest of the report are unchanged."""
    if rep.model is None or rep.company is None:
        raise ValueError("This report has no valuation to analyse news against.")
    import copy

    old = rep
    rep = copy.copy(rep)  # the shown report is untouched until the refresh succeeds
    rep.guard_log = list(old.guard_log)
    p = Progress(None)
    p.status.update(rep.desk_status or {})
    # A refresh is its own run for MAX_COST_PER_REPORT (the daily cap still covers it); its cost is added to the
    # report's total below.
    run_id = f"{rep.report_id}/news-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}"
    filing = None
    try:
        filing = latest_annual_report(svc, rep.company.profile.statements_cik)
    except (DataSourceError, CacheMiss, KeyError):
        pass
    sources = _sources_text(rep.research, filing)
    exposure = rep.exposure or build_exposure(rep.company, rep.research)
    rep.exposure = exposure
    p("News desk", RUNNING, "Refreshing news…")
    names = [getattr(x, "name", None) or getattr(x, "ticker", "") for x in rep.peers_pool][:6]
    try:
        rep.news = run_news(svc.ai, svc, run_id, rep.company, exposure, [n for n in names if n], force=True)
    except Exception as exc:  # keep the saved news rather than replace it with a failure
        raise RuntimeError(f"the news search failed ({type(exc).__name__}: {exc}); the saved news is unchanged") \
            from exc
    p("News desk", DONE, f"Refreshed: {len(rep.news.items)} items")
    summary = {**build_summary(rep.model, _research_for_ai(rep.research)), **extras_for_ai(rep)}
    try:
        rep.impact = _impact_job(svc, run_id, rep.model, rep.news, exposure, summary, sources, p,
                                 lambda: svc.ai.report_cost(run_id))
    except CostCapExceeded as exc:
        p("Impact analyst", FAILED, str(exc))
        rep.impact = None
    if rep.impact and rep.impact.items and not rep.impact.error:
        try:
            run_news_view(svc.ai, run_id, rep.impact, rep.md.rating if rep.md else None,
                          rep.md.conviction if rep.md else None, sources)
        except Exception as exc:
            rep.impact.notes.append(f"The MD's news summary could not be written: {exc}")
    if rep.impact:
        rep.guard_log += rep.impact.guard_log
        if rep.md:
            rep.impact.notes.append(f"News refreshed on {rep.news.as_of[:16].replace('T', ' ')} UTC; the rating "
                                    f"and rubric are from the original run ({rep.created_at[:16].replace('T', ' ')} "
                                    "UTC).")
    rep.ai_cost += svc.ai.report_cost(run_id)
    rep.desk_status = dict(p.status)
    try:
        save(rep, svc.store)
        rep.save_error = None
    except Exception as exc:
        rep.save_error = f"The refreshed news could not be saved ({type(exc).__name__}: {exc})."
    return rep


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
