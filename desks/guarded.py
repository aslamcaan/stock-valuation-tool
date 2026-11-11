"""Guarded AI call: number-check every text field; regenerate once; then drop failing sentences and log them."""
from __future__ import annotations

import json
import re

from desks.ai import AIClient, CostCapExceeded
from desks.dcf_guard import drop_wrong_dcf
from desks.number_guard import apply_cleaning, check_fields, flatten_numbers, numbers_from_text, strings_in

SKIP_KEYS = {"criterion", "stage", "suggested_stage", "view", "severity", "side", "conviction", "code", "level"}


def _without(data, keys):
    if isinstance(data, dict):
        return {k: _without(v, keys) for k, v in data.items() if k not in keys}
    if isinstance(data, list):
        return [_without(v, keys) for v in data]
    return data


# A date field must be a date or period, not prose that could carry an unchecked number. Date fields are skipped by
# the number check, so they are validated here instead.
DATE_OK = re.compile(r"^((date )?not disclosed|\d{4}-\d{2}(-\d{2})?|(Q[1-4]|H[12]|FY) ?\d{4}|"
                     r"(early|mid|late) \d{4}|\d{1,2} [A-Z][a-z]+ \d{4}|[A-Z][a-z]+ \d{1,2},? \d{4}|[A-Z][a-z]+ \d{4})$")
CODE_TEXT = ("flags", "insider_activity", "forensic", "major_holders", "short_interest")

def thresholds(payload: dict) -> list[float]:
    """The brief's rule limits: quotable only in a sentence that talks about a limit or threshold."""
    return flatten_numbers(payload.get("rule_thresholds", {})) if isinstance(payload, dict) else []


def allowed_numbers(payload: dict, quotable=()) -> list[float]:
    allowed = flatten_numbers({k: v for k, v in payload.items() if k != "rule_thresholds"})
    # figures in the research desk's extracts were verified against the filing, so they may be quoted
    allowed += [x for s in strings_in(payload.get("research", {})) for x in numbers_from_text(s)]
    # code-written text (flag messages, ownership and forensic notes) states computed figures, so they may be quoted
    allowed += [x for k in CODE_TEXT for s in strings_in(payload.get(k, {})) for x in numbers_from_text(s)]
    allowed += [x for s in quotable for x in numbers_from_text(s)]
    return allowed


def recheck(data: dict, payload: dict, sources: str, desk: str, skip=frozenset()) -> tuple[dict, list[str]]:
    """Check text written earlier against NEW computed results (e.g. after the model was re-run) and drop sentences
    whose numbers no longer exist. No regeneration."""
    skip_keys = SKIP_KEYS | set(skip)
    results = check_fields(_without(data, skip_keys), allowed_numbers(payload), sources,
                           contextual=thresholds(payload))
    bad = {k: r for k, r in results.items() if not r.ok}
    log = [f"{desk}: dropped after the model was re-run, from {k}: \"{s[:160]}\" (no longer in the results: "
           f"{', '.join(r.bad_numbers)})" for k, r in bad.items() for s in r.bad_sentences]
    if bad:
        data = _merge_back(data, apply_cleaning(_without(data, skip_keys), results))
    return data, log


def guarded_call(ai: AIClient, *, report_id: str, desk: str, model: str, system: str, payload: dict, schema: dict,
                 sources: str, instructions: str, effort: str = "medium", max_tokens: int = 16000,
                 skip: set[str] | frozenset = frozenset(), quotable: list[str] = ()) -> tuple[dict, list[str]]:
    """Returns (data, guard_log). `payload` holds the computed results the desk may quote. `skip` names extra keys
    that hold ids, enums or dates rather than prose (not number-checked). `quotable` is fetched text (news headlines
    and summaries) whose own figures may be quoted, as the source says them."""
    skip_keys = SKIP_KEYS | set(skip)
    allowed = allowed_numbers(payload, quotable)
    sources = "\n".join([sources, *quotable])  # non-US$ amounts and quotes may come verbatim from the news too
    content = (f"{instructions}\n\n<document name=\"computed results\">\n{json.dumps(payload, default=str)}\n"
               f"</document>")
    data = ai.call(report_id=report_id, desk=desk, model=model, system=system, content=content, schema=schema,
                   effort=effort, max_tokens=max_tokens)
    results = check_fields(_without(data, skip_keys), allowed, sources, contextual=thresholds(payload))
    bad = {k: r for k, r in results.items() if not r.ok}
    log: list[str] = []
    if bad:
        nums = sorted({n for r in bad.values() for n in r.bad_numbers})
        retry = (content + "\n\nYour previous answer used numbers that are not in the computed results or the quoted "
                 f"sources: {', '.join(nums[:20])}. Rewrite it using only numbers that appear in the computed results, "
                 "rounded as shown, or verbatim quotes from the sources.")
        try:
            data = ai.call(report_id=report_id, desk=desk, model=model, system=system, content=retry, schema=schema,
                           effort=effort, max_tokens=max_tokens)
        except CostCapExceeded:  # no budget to regenerate: keep the first answer without the failing sentences
            log.append(f"{desk}: not regenerated (AI cost cap); unsupported sentences dropped instead")
        else:
            results = check_fields(_without(data, skip_keys), allowed, sources, contextual=thresholds(payload))
            bad = {k: r for k, r in results.items() if not r.ok}
            log.append(f"{desk}: regenerated once because of unsupported numbers ({', '.join(nums[:8])})")
        if bad:
            for k, r in bad.items():
                for s in r.bad_sentences:
                    log.append(f"{desk}: dropped from {k}: \"{s[:160]}\" (unsupported: {', '.join(r.bad_numbers)})")
            cleaned = apply_cleaning(_without(data, skip_keys), results)
            data = _merge_back(data, cleaned)
    # one DCF per report: a dollar figure labelled DCF must be one the model computed
    data, dcf_log = drop_wrong_dcf(data, payload, desk)
    return data, log + dcf_log


def _merge_back(original, cleaned):
    if isinstance(original, dict):
        return {k: (_merge_back(v, cleaned[k]) if k in cleaned else v) for k, v in original.items()}
    if isinstance(original, list):
        return [_merge_back(o, c) for o, c in zip(original, cleaned)]
    return cleaned
