"""One rating per report. The MD writes its view in the same AI call that scores the rubric, and code turns the scores
into the final rating afterwards, so the AI cannot know it. Any sentence of AI text that names a rating other than the
final one is dropped (and logged), so the written report never disagrees with the rating in the header."""
from __future__ import annotations

import re

from desks.number_guard import SENTENCE_RE

RATING_RE = re.compile(r"\b(Strong Buy|Strong Sell|Buy|Hold|Sell)\b(?![-\w])")
SKIP_KEYS = {"criterion", "side", "conviction", "date", "level", "code", "stage", "severity"}


def _mismatch(sentence: str, allowed: set[str]) -> list[str]:
    return [m for m in RATING_RE.findall(sentence) if m not in allowed]


def _clean_text(text: str, allowed: set[str]) -> tuple[str, list[tuple[str, list[str]]]]:
    kept, dropped = [], []
    for s in SENTENCE_RE.split(text.strip()) if text.strip() else []:
        bad = _mismatch(s, allowed)
        if bad:
            dropped.append((s, bad))
        else:
            kept.append(s)
    return " ".join(kept), dropped


def drop_wrong_ratings(data, final: str, desk: str, also_allowed: dict[str, set[str]] | None = None,
                       path: str = "") -> tuple[object, list[str]]:
    """`final` is the one rating the text may name. `also_allowed` maps a field name to extra ratings that field may
    name (the notch reason and the rating-vs-verdict explanation talk about the rubric rating too).
    Returns (cleaned copy, log lines)."""
    log: list[str] = []
    also_allowed = also_allowed or {}
    if isinstance(data, dict):
        out = {}
        for k, v in data.items():
            if k in SKIP_KEYS:
                out[k] = v
                continue
            out[k], sub = drop_wrong_ratings(v, final, desk, also_allowed, f"{path}.{k}" if path else k)
            log += sub
        return out, log
    if isinstance(data, list):
        out = []
        for i, v in enumerate(data):
            cleaned, sub = drop_wrong_ratings(v, final, desk, also_allowed, f"{path}[{i}]")
            log += sub
            if isinstance(v, str) and v.strip() and not cleaned:
                continue  # the whole line named another rating: remove it rather than leave an empty bullet
            out.append(cleaned)
        return out, log
    if isinstance(data, str):
        field = re.sub(r"\[\d+\]", "", path).split(".")[-1]
        allowed = {final} | also_allowed.get(field, set())
        cleaned, dropped = _clean_text(data, allowed)
        for s, bad in dropped:
            log.append(f"{desk}: dropped from {path}: \"{s[:160]}\" (names {', '.join(sorted(set(bad)))}; "
                       f"the report's rating is {final})")
        return cleaned, log
    return data, log
