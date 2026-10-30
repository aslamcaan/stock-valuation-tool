"""Review desk (AI, Sonnet): challenges assumptions, explains flags, judges the cycle and the stage, and writes
the strongest bear case (and bull case, used when the rating is Sell). Proposes; code decides what changes."""
from __future__ import annotations

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
For a bank, insurer or REIT (the results have a "toolkit" instead of a "stage"): there is no DCF and no lifecycle
stage, so set stage_review to agree with suggested_stage "none", and challenge the toolkit's assumptions instead
(normalised return, cost of equity, long-run growth, cap rate, peer set, reported vs computed metrics, credit or
underwriting quality, capital).
Rules: never calculate. Only use numbers that appear in the computed results (rounded as shown) or verbatim in the
filing quotes. Write in UK English, concise, specific to this company."""


def run_review(ai: AIClient, report_id: str, summary: dict, sources: str) -> tuple[dict, list[str]]:
    return guarded_call(ai, report_id=report_id, desk="Review desk", model=SONNET, system=SYSTEM, payload=summary,
                        schema=SCHEMA, sources=sources, effort="medium",
                        instructions="Review this valuation.")
