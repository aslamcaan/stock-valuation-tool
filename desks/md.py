"""MD (AI + code): scores the AI half of the rubric with evidence, proposes at most a one-notch move, and writes
the investment view. Code scores the other half, maps the weighted score to the rating and applies the notch."""
from __future__ import annotations

from dataclasses import dataclass, field

from desks.ai import SONNET, AIClient
from desks.guarded import DATE_OK, guarded_call
from desks.rating_guard import drop_wrong_ratings
from desks.research import _arr, _obj
from engine.rubric import (AI_CRITERIA, LABELS, Score, apply_notch, conflicts_with_verdict, gate_by_evidence,
                           gate_by_verdict, rating_from,
                           score_business_quality, score_financial_quality, score_financial_strength,
                           score_financial_strength_sector, score_revisions, score_valuation_gap)

_S = {"type": "string"}

SCHEMA = _obj({
    "ai_scores": _arr(_obj({"criterion": {"type": "string", "enum": AI_CRITERIA},
                            "score": {"type": "integer", "enum": [1, 2, 3, 4, 5]}, "evidence": _S})),
    "notch": {"type": "integer", "enum": [-1, 0, 1]},
    "notch_reason": _S,
    "conviction": {"type": "string", "enum": ["High", "Medium", "Low"]},
    "thesis": _S,
    "reasoning_lines": _arr(_S),
    "bull_vs_bear": _obj({"side": {"type": "string", "enum": ["bull", "bear", "balanced"]}, "why": _S}),
    "bear_case_response": _S,
    "bull_case_response": _S,
    "what_has_to_be_true": _arr(_S),
    "catalysts": _arr(_obj({"event": _S, "date": _S, "why": _S})),
    "what_would_change_view": _arr(_S),
    "rating_vs_verdict_explanation": _S,
    "key_risks": _arr(_obj({"risk": _S, "quote": _S})),
})

SYSTEM = """You are the managing director (MD) who signs off an equity research report. You receive the computed
valuation, the review desk's challenges with its bear and bull cases, the research desk's filing extracts, and the
code-scored half of the rating rubric. Your job:
1. Score the five qualitative criteria 1-5 (5 = best for shareholders) with specific evidence from the filing quotes
   or results: moat (competitive position), management (track record and capital allocation), governance (founder
   control, dual-class shares, related parties), industry (outlook), catalysts (upcoming events and news flow: use
   "news", the impact analyst's computed effects and whether each is priced in, when it is given; an effect that is
   unquantified or from an Unverified source counts for less).
2. The code maps the weighted score to a rating. You may propose moving it by one notch (-1, 0, +1) only with a
   specific written reason; otherwise 0.
3. Write the investment view: a thesis, 3-4 short reasoning lines for the verdict card, which side of the bull/bear
   debate you take and why, a direct response to the review desk's bear case (and to its bull case), 2-3 things that
   have to be true, catalysts with dates (from the filing or results; say "date not disclosed" if unknown), and what
   would change your view. The next results date is in calendar.next_earnings when an earnings calendar gave one:
   use it for the earnings catalyst (date as YYYY-MM-DD). News published since calendar.price_as_of is the most
   recent: list material items from "news" among the catalysts, with their dates. Give the 3-5 key risks, each with a verbatim quote from the filing extracts.
4. Never name a rating (Strong Buy, Buy, Hold, Sell, Strong Sell) in any text field. Code turns the scores into the
   rating after you reply and shows it separately, so any rating you name may not match it. Refer to the valuation
   verdict (Undervalued, Fairly valued, Overvalued), the score and the evidence instead. Only notch_reason and
   rating_vs_verdict_explanation may name a rating, and only when they say how the rubric rating was moved.
   The rating cannot point against the valuation: an Overvalued verdict caps it at Hold and an Undervalued verdict
   floors it at Hold, whatever the quality scores. Write the view to be consistent with that (a great business at
   too high a price does not earn a buy). If the weighted score alone would point the other way, say so in
   rating_vs_verdict_explanation; otherwise leave it empty.
   The code also checks the rating against "rating_evidence": a buy needs the price below the bull-case DCF and at
   least 30% of Monte Carlo runs above the price, and a fair value more than 30% below the price cannot be a hold.
   Write the view to match that evidence.
Rules: never calculate. Only use numbers from the computed results (rounded as shown) or verbatim filing quotes.
UK English. Be decisive and specific.
Write ratios such as margins, ROIC, WACC and growth as percentages to one decimal (30.9%), never as decimals (0.309); money with its unit ($10.1bn, $116m)."""


@dataclass
class MDResult:
    scores: list[Score]
    weighted_score: float
    code_rating: str
    rating: str
    conviction: str
    view: dict
    conflict: bool
    guard_log: list[str] = field(default_factory=list)
    gate_note: str = ""  # set when the verdict gate moved the rating


MAX_TOKENS = 6000  # the sign-off is about 2,200 tokens; the cap sets the worst-case cost reservation

def code_scores(report) -> list[Score]:
    fv = getattr(report, "financial", None)
    if fv is not None:  # banks, insurers, REITs
        def m(key):
            x = fv.metric(key)
            if x is None:
                return None
            return x.reported.value if x.reported is not None else x.value.value
        label = {"bank": "ROTE", "insurer": "ROE"}.get(fv.toolkit, "return")
        quality = score_financial_quality(fv.normalised_return.value if fv.normalised_return else None,
                                          fv.cost_of_equity.value, label) if fv.toolkit != "reit" else             Score("business_quality", 3, "REIT: judged by the MD on portfolio quality; neutral code score", "code")
        return [score_valuation_gap(report.verdict.gap), quality,
                score_financial_strength_sector(fv.toolkit, cet1=m("cet1_ratio"), combined_ratio=m("combined_ratio"),
                                                debt_to_ebitda=m("debt_to_ebitda")),
                score_revisions(report.revisions)]
    cd, v, vd = report.company, report.valuation, report.verdict
    h = cd.historicals_usd
    p = h.ltm.label if h.ltm else h.fy_labels[-1]
    roic = cd.analysis.m("roic", h.fy_labels[-1])
    margin_pct = report.comps.benchmarks["operating_margin"]["percentile"] if report.comps else None
    return [score_valuation_gap(vd.gap), score_business_quality(roic, v.wacc.wacc.value, margin_pct),
            score_financial_strength(h.v("net_debt", p), h.v("ebitda", p),
                                     cd.analysis.m("interest_cover", p) or cd.analysis.m("interest_cover", h.fy_labels[-1])),
            score_revisions(report.revisions)]


def run_md(ai: AIClient, report_id: str, report, summary: dict, review: dict, sources: str,
           news: dict | None = None, evidence: dict | None = None) -> MDResult:
    """`news` is the impact analyst's computed payload (desks.impact.impact_payload), when the news desk ran.
    `evidence` holds fair_value, price, dcf_bull and prob_above (the Monte Carlo share above the price): the rating may
    not point against it (engine.rubric.gate_by_evidence)."""
    codes = code_scores(report)
    payload = {**summary, "review_desk": review,
               "code_scores": [{"criterion": LABELS[s.criterion], "score": s.score, "evidence": s.evidence}
                               for s in codes]}
    if evidence:
        payload["rating_evidence"] = {k: (None if x is None else round(float(x), 4 if k == "prob_above" else 2))
                                      for k, x in evidence.items()}
    if news:
        payload["news"] = news
    data, log = guarded_call(ai, report_id=report_id, desk="MD", model=SONNET, system=SYSTEM, payload=payload,
                             schema=SCHEMA, sources=sources, effort="medium", max_tokens=MAX_TOKENS,
                             instructions="Sign off this report.", skip={"date"})
    for c in data.get("catalysts", []):  # dates skip the number check, so they must be dates
        if not DATE_OK.match(c["date"].strip()):
            c["date"] = "date not disclosed"
    ai_scores = []
    seen = set()
    for s in data["ai_scores"]:
        if s["criterion"] not in seen:
            seen.add(s["criterion"])
            ai_scores.append(Score(s["criterion"], int(s["score"]), s["evidence"], "MD"))
    for c in AI_CRITERIA:  # a criterion the MD skipped counts as neutral, and says so
        if c not in seen:
            ai_scores.append(Score(c, 3, "not scored by the MD: neutral", "MD"))
    scores = codes + ai_scores
    avg, code_rating = rating_from(scores)
    notch = int(data["notch"]) if data.get("notch_reason") else 0
    rating = apply_notch(code_rating, notch)
    conflict = conflicts_with_verdict(rating, report.verdict.verdict)
    if conflict and not data.get("rating_vs_verdict_explanation"):
        log.append("MD: rating conflicts with the valuation verdict but no explanation was given; notch removed")
        rating = code_rating
        conflict = conflicts_with_verdict(rating, report.verdict.verdict)
    notched = rating
    rating, gate = gate_by_verdict(rating, report.verdict.verdict)
    ev_notes: list[str] = []
    if evidence:
        rating, ev_notes = gate_by_evidence(rating, **evidence)
    if gate or ev_notes:
        conflict = False
        gate = "; ".join([g for g in [gate, *ev_notes] if g])
    # one rating per report: text written before the rating existed may not name a different one
    named_ok = {"notch_reason": {code_rating, notched}, "rating_vs_verdict_explanation": {code_rating, notched}}
    data, wrong = drop_wrong_ratings(data, rating, "MD", named_ok)
    log += wrong
    return MDResult(scores, avg, code_rating, rating, data["conviction"], data, conflict, log, gate)
