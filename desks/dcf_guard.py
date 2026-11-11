"""One DCF per report. Every figure the text labels as a DCF value must be one of the computed DCF figures (base case,
bear, base, bull, probability-weighted, structural case) or the price or fair value the sentence may be comparing it
with. A sentence that puts another dollar figure next to "DCF" is dropped and logged, so the written report cannot
quote a DCF value that differs from the one the model computed."""
from __future__ import annotations

import re

from desks.number_guard import SENTENCE_RE

# a per-share amount (no unit suffix such as bn or m) within 60 characters after the word DCF
_NEAR = re.compile(r"\bDCF\b[^$]{0,60}?\$\s?(\d[\d,]*(?:\.\d+)?)(?!\.?\d)(?!,\d)(?!\s?(?:bn|billion|m\b|million|k\b|trillion|tn))")
SKIP_KEYS = {"criterion", "side", "conviction", "date", "level", "code", "stage", "severity", "suggested_stage", "view"}


def computed_dcf_values(payload: dict) -> set[float]:
    """Per-share values a sentence may legitimately put next to the word DCF."""
    vals: list = []
    dcf = payload.get("dcf") or {}
    vals += list((dcf.get("figures") or {}).values())
    vals += [dcf.get("value_per_share"), dcf.get("structural_case_value")]
    vals += [s.get("value") for s in (dcf.get("scenarios") or {}).values()]
    v = payload.get("verdict") or {}
    vals += [(v.get("components") or {}).get("dcf"), v.get("fair_value"), v.get("blend_fair_value"),
             payload.get("price")]  # a sum-of-the-parts component is named "sum_of_the_parts", so it is not allowed here
    return {round(float(x), 2) for x in vals if isinstance(x, (int, float)) and not isinstance(x, bool)}


def _ok(amount: float, allowed: set[float]) -> bool:
    return any(abs(amount - a) <= max(0.0051, 0.0006 * abs(a)) for a in allowed)


def drop_wrong_dcf(data, payload: dict, desk: str, path: str = "", _allowed: set[float] | None = None):
    """Returns (cleaned copy, log lines). Does nothing when the payload carries no DCF (banks, insurers, REITs)."""
    if not isinstance(payload, dict) or not payload.get("dcf"):
        return data, []
    allowed = _allowed if _allowed is not None else computed_dcf_values(payload)
    log: list[str] = []
    if isinstance(data, dict):
        out = {}
        for k, v in data.items():
            if k in SKIP_KEYS:
                out[k] = v
                continue
            out[k], sub = drop_wrong_dcf(v, payload, desk, f"{path}.{k}" if path else k, allowed)
            log += sub
        return out, log
    if isinstance(data, list):
        out = []
        for i, v in enumerate(data):
            cleaned, sub = drop_wrong_dcf(v, payload, desk, f"{path}[{i}]", allowed)
            log += sub
            if isinstance(v, str) and v.strip() and not cleaned:
                continue
            out.append(cleaned)
        return out, log
    if isinstance(data, str):
        kept = []
        for s in SENTENCE_RE.split(data.strip()) if data.strip() else []:
            bad = [m for m in _NEAR.findall(s) if not _ok(float(m.replace(",", "")), allowed)]
            if bad:
                log.append(f"{desk}: dropped from {path}: \"{s[:160]}\" (DCF figure ${', $'.join(bad)} is not a "
                           "computed DCF value of this report)")
            else:
                kept.append(s)
        return " ".join(kept), log
    return data, log
