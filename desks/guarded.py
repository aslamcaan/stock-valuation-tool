"""Guarded AI call: number-check every text field; regenerate once; then drop failing sentences and log them."""
from __future__ import annotations

import json

from desks.ai import AIClient
from desks.number_guard import apply_cleaning, check_fields, flatten_numbers, numbers_from_text, strings_in

SKIP_KEYS = {"criterion", "stage", "suggested_stage", "view", "severity", "side", "conviction", "code", "level"}


def _without(data, keys):
    if isinstance(data, dict):
        return {k: _without(v, keys) for k, v in data.items() if k not in keys}
    if isinstance(data, list):
        return [_without(v, keys) for v in data]
    return data


def guarded_call(ai: AIClient, *, report_id: str, desk: str, model: str, system: str, payload: dict, schema: dict,
                 sources: str, instructions: str, effort: str = "medium", max_tokens: int = 16000
                 ) -> tuple[dict, list[str]]:
    """Returns (data, guard_log). `payload` holds the computed results the desk may quote."""
    allowed = flatten_numbers(payload)
    # figures in the research desk's extracts were verified against the filing, so they may be quoted
    allowed += [x for s in strings_in(payload.get("research", {})) for x in numbers_from_text(s)]
    content = (f"{instructions}\n\n<document name=\"computed results\">\n{json.dumps(payload, default=str)}\n"
               f"</document>")
    data = ai.call(report_id=report_id, desk=desk, model=model, system=system, content=content, schema=schema,
                   effort=effort, max_tokens=max_tokens)
    results = check_fields(_without(data, SKIP_KEYS), allowed, sources)
    bad = {k: r for k, r in results.items() if not r.ok}
    log: list[str] = []
    if bad:
        nums = sorted({n for r in bad.values() for n in r.bad_numbers})
        retry = (content + "\n\nYour previous answer used numbers that are not in the computed results or the quoted "
                 f"sources: {', '.join(nums[:20])}. Rewrite it using only numbers that appear in the computed results, "
                 "rounded as shown, or verbatim quotes from the sources.")
        data = ai.call(report_id=report_id, desk=desk, model=model, system=system, content=retry, schema=schema,
                       effort=effort, max_tokens=max_tokens)
        results = check_fields(_without(data, SKIP_KEYS), allowed, sources)
        bad = {k: r for k, r in results.items() if not r.ok}
        log.append(f"{desk}: regenerated once because of unsupported numbers ({', '.join(nums[:8])})")
        if bad:
            for k, r in bad.items():
                for s in r.bad_sentences:
                    log.append(f"{desk}: dropped from {k}: \"{s[:160]}\" (unsupported: {', '.join(r.bad_numbers)})")
            cleaned = apply_cleaning(_without(data, SKIP_KEYS), results)
            data = _merge_back(data, cleaned)
    return data, log


def _merge_back(original, cleaned):
    if isinstance(original, dict):
        return {k: (_merge_back(v, cleaned[k]) if k in cleaned else v) for k, v in original.items()}
    if isinstance(original, list):
        return [_merge_back(o, c) for o, c in zip(original, cleaned)]
    return cleaned
