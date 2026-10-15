"""MD (AI + code): scores the AI half of the rubric with evidence, proposes at most a one-notch move, and writes
the investment view. Code scores the other half, maps the weighted score to the rating and applies the notch."""
from __future__ import annotations

from dataclasses import dataclass, field

from desks.ai import SONNET, AIClient
from desks.guarded import guarded_call
from desks.research import _arr, _obj
from engine.rubric import (AI_CRITERIA, LABELS, Score, apply_notch, conflicts_with_verdict, rating_from,
                           score_business_quality, score_financial_strength, score_revisions, score_valuation_gap)

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
   control, dual-class shares, related parties), industry (outlook), catalysts (upcoming events and news flow).
2. The code maps the weighted score to a rating. You may propose moving it by one notch (-1, 0, +1) only with a
   specific written reason; otherwise 0.
3. Write the investment view: a thesis, 3-4 short reasoning lines for the verdict card, which side of the bull/bear
   debate you take and why, a direct response to the review desk's bear case (and to its bull case), 2-3 things that
   have to be true, catalysts with dates (from the filing or results; say "date not disclosed" if unknown), and what
   would change your view. Give the 3-5 key risks, each with a verbatim quote from the filing extracts.
4. If your rating and the valuation verdict point in opposite directions (e.g. Buy on an overvalued stock), explain
   why explicitly in rating_vs_verdict_explanation; otherwise leave it empty.
Rules: never calculate. Only use numbers from the computed results (rounded as shown) or verbatim filing quotes.
UK English. Be decisive and specific."""


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


def code_scores(report) -> list[Score]:
    cd, v, vd = report.company, report.valuation, report.verdict
    h = cd.historicals_usd
    p = h.ltm.label if h.ltm else h.fy_labels[-1]
    roic = cd.analysis.m("roic", h.fy_labels[-1])
    margin_pct = report.comps.benchmarks["operating_margin"]["percentile"] if report.comps else None
    return [score_valuation_gap(vd.gap), score_business_quality(roic, v.wacc.wacc.value, margin_pct),
            score_financial_strength(h.v("net_debt", p), h.v("ebitda", p),
                                     cd.analysis.m("interest_cover", p) or cd.analysis.m("interest_cover", h.fy_labels[-1])),
            score_revisions(report.revisions)]


def run_md(ai: AIClient, report_id: str, report, summary: dict, review: dict, sources: str) -> MDResult:
    codes = code_scores(report)
    payload = {**summary, "review_desk": review,
               "code_scores": [{"criterion": LABELS[s.criterion], "score": s.score, "evidence": s.evidence}
                               for s in codes]}
    data, log = guarded_call(ai, report_id=report_id, desk="MD", model=SONNET, system=SYSTEM, payload=payload,
                             schema=SCHEMA, sources=sources, effort="medium", instructions="Sign off this report.")
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
    return MDResult(scores, avg, code_rating, rating, data["conviction"], data, conflict, log)
