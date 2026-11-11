"""Review desk (AI, Sonnet): challenges assumptions, explains flags, judges the cycle and the stage, and writes
the strongest bear case (and bull case, used when the rating is Sell). Proposes; code decides what changes."""
from __future__ import annotations

import re

from desks.ai import SONNET, AIClient
from desks.guarded import guarded_call
from desks.research import _arr, _obj

_S = {"type": "string"}
STAGES = ["early", "high_growth", "mature_growth", "mature_stable", "cyclical", "declining"]

SCHEMA = _obj({
    "challenges": _arr(_obj({"assumption": _S, "challenge": _S, "evidence": _S,
                             "severity": {"type": "string", "enum": ["high", "medium", "low"]},
                             "resolution": _S})),
    "stage_review": _obj({"agree": {"type": "boolean"},
                          "suggested_stage": {"type": "string", "enum": STAGES + ["none"]}, "reason": _S}),
    "cycle_judgement": _obj({"view": {"type": "string",
                                      "enum": ["cyclical_peak", "trough", "structural_shift", "mid_cycle",
                                               "not_applicable"]},
                             "evidence": _S}),
    "bear_case": _obj({"thesis": _S, "points": _arr(_S)}),
    "bull_case": _obj({"thesis": _S, "points": _arr(_S)}),
    "flag_explanations": _arr(_obj({"code": _S, "explanation": _S})),
    "headline_check": _obj({"credible": {"type": "boolean"},
                            "target": {"type": "string", "enum": ["fair_value", "blend", "margin_path", "growth_path",
                                                                  "none"]},
                            "reason": _S}),
})

SYSTEM = """You are the review desk of an equity research team: a sceptical senior analyst. You receive the computed
valuation (all numbers come from code) and the research desk's filing extracts. Your job:
1. Challenge the 3-6 assumptions most likely to be wrong (growth, margins, reinvestment, WACC inputs, terminal value,
   peer set), with evidence from the results or the filing quotes, and say how each should be resolved.
2. Review the lifecycle stage classification: agree, or suggest another stage with a written reason.
3. Cycle judgement: if margins are volatile or near a 10-year high or low, judge with evidence whether current results
   are a cyclical peak, a trough, or a structural shift (new product, pricing power, consolidation). Otherwise
   "not_applicable".
4. Write the strongest possible bear case, and the strongest possible bull case, each as a thesis plus 3-5 points.
5. Explain each amber or red flag in plain English: what it means for this company.
6. Headline check: is the headline fair value credible? Set credible to false (with the target: fair_value, blend,
   margin_path or growth_path, and the reason) if you would tell the portfolio manager to discard the headline figure
   as it stands, for example because the blend mixes methods that disagree wildly, or a margin or growth path is far
   outside anything the company has achieved. Otherwise credible is true and target is "none".
Quote a DCF value only from dcf.figures (base_case, bear, base, bull, probability_weighted, structural): the report has
one DCF, and any other dollar figure next to the word DCF is removed.
For a bank, insurer or REIT (the results have a "toolkit" instead of a "stage"): there is no DCF and no lifecycle
stage, so set stage_review to agree with suggested_stage "none", and challenge the toolkit's assumptions instead
(normalised return, cost of equity, long-run growth, cap rate, peer set, reported vs computed metrics, credit or
underwriting quality, capital).
Rules: never calculate. Only use numbers that appear in the computed results (rounded as shown) or verbatim in the
filing quotes. Write in UK English, concise, specific to this company.
Write ratios such as margins, ROIC, WACC and growth as percentages to one decimal (30.9%), never as decimals (0.309); money with its unit ($10.1bn, $116m). Multiples are written as multiples, never as percentages: net debt to EBITDA, interest cover, EV/EBITDA and P/E as 0.1x, 12.4x, never 8.2%."""


# a high-severity challenge whose subject is one of these questions the headline number itself
HEADLINE_SUBJECT = re.compile(r"fair value|blend|headline|margin|growth|verdict", re.I)


def headline_challenge(review: dict | None) -> str | None:
    """Why the blended fair value must not be used for the verdict, or None. It fires when the review desk says the
    headline is not credible, or raises a high-severity challenge on the fair value, the blend, the margin path or the
    growth path."""
    if not review:
        return None
    hc = review.get("headline_check") or {}
    if hc.get("credible") is False:
        why = (hc.get("reason") or "").strip()
        return "The review desk judged the blended fair value not credible" + (f": {why}" if why else ".")
    for c in review.get("challenges", []):
        if c.get("severity") == "high" and HEADLINE_SUBJECT.search(c.get("assumption", "")):
            sub = c["assumption"].strip().rstrip(".")
            return f"The review desk raised a high-severity challenge on {sub}: {_first_sentence(c.get('challenge', ''))}"
    return None


def _first_sentence(text: str) -> str:
    t = (text or "").strip()
    m = re.search(r"(?<=[.!?])\s", t)
    return t[:m.start()] if m else t


def run_review(ai: AIClient, report_id: str, summary: dict, sources: str) -> tuple[dict, list[str]]:
    return guarded_call(ai, report_id=report_id, desk="Review desk", model=SONNET, system=SYSTEM, payload=summary,
                        schema=SCHEMA, sources=sources, effort="medium",
                        instructions="Review this valuation.")
