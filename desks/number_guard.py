"""Number guard (pure): every number in AI-written text must exist in the computed results (CLAUDE.md AI RULES).

Matching normalises units and allows rounding to the precision shown in the text:
- "$1.1bn" matches 1,110 (US$ millions); "45.2m" matches 45.2 (millions); "2,799" matches 2,799.
- "12.3%" matches a ratio of 0.123 (or a value already in percent); "2.4x" matches 2.4.
- Tolerance is half a unit of the last shown digit (1.1 -> +/-0.05), with a 0.5% relative floor.
Exempt: years (1990-2100), fiscal labels (FY2025, Q3, H1), and small counts (integers up to 10).
Numbers inside quotation marks are exempt only if the quote appears verbatim in the source text supplied.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

NUM_RE = re.compile(
    r"(?P<cur>US\$|\$|€|£|S\$)?\s?(?P<num>-?\d{1,3}(?:,\d{3})+(?:\.\d+)?|-?\d+(?:\.\d+)?)\s?"
    r"(?P<unit>%|bps|bp|x|bn|billion|mn|million|m|k|thousand|trillion|tn)?(?![A-Za-z0-9])", re.IGNORECASE)
LABEL_RE = re.compile(r"\b(?:FY|Q|H)\d{1,4}\b|\b(?:19|20)\d{2}[-/]\d{2}(?:[-/]\d{2})?\b", re.IGNORECASE)
QUOTE_RE = re.compile(r"[\"“”']([^\"“”']{8,})[\"“”']")
SENTENCE_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z(])")


@dataclass
class GuardResult:
    ok: bool
    bad_numbers: list[str] = field(default_factory=list)
    bad_sentences: list[str] = field(default_factory=list)
    cleaned: str = ""


def flatten_numbers(obj, out: list[float] | None = None) -> list[float]:
    """All finite numbers inside nested dicts / lists / objects with a .value."""
    out = [] if out is None else out
    if isinstance(obj, bool) or obj is None:
        return out
    if isinstance(obj, (int, float)):
        if math.isfinite(obj):
            out.append(float(obj))
    elif isinstance(obj, dict):
        for v in obj.values():
            flatten_numbers(v, out)
    elif isinstance(obj, (list, tuple, set)):
        for v in obj:
            flatten_numbers(v, out)
    elif hasattr(obj, "value"):
        flatten_numbers(obj.value, out)
    return out


def numbers_from_text(text: str) -> list[float]:
    """Numbers written in verified source text (e.g. research-desk extracts), in every unit reading.
    "$193,454 million" -> 193454; "$5.0 billion" -> 5000; "18%" -> 0.18 and 18."""
    out: list[float] = []
    for m in NUM_RE.finditer(text or ""):
        out += _candidates(float(m.group("num").replace(",", "")), m.group("unit"))
    return out


def strings_in(obj) -> list[str]:
    if isinstance(obj, str):
        return [obj]
    if isinstance(obj, dict):
        return [s for v in obj.values() for s in strings_in(v)]
    if isinstance(obj, (list, tuple)):
        return [s for v in obj for s in strings_in(v)]
    return []


def _candidates(num: float, unit: str | None) -> list[float]:
    """Values (in the results' base units) that a written number could stand for."""
    u = (unit or "").lower()
    if u in ("%",):
        return [num / 100, num]
    if u in ("bp", "bps"):
        return [num / 10000]
    if u in ("bn", "billion"):
        return [num * 1000, num * 1e9]
    if u in ("tn", "trillion"):
        return [num * 1e6, num * 1e12]
    if u in ("m", "mn", "million"):
        return [num, num * 1e6]
    if u in ("k", "thousand"):
        return [num / 1000, num * 1000]
    return [num, num / 100]  # bare numbers may be percentages written without a sign


def _tolerance(text_num: str, unit: str | None) -> float:
    decimals = len(text_num.split(".")[1]) if "." in text_num else 0
    return 0.5 * 10 ** (-decimals)


def _scaled_tol(tol: float, unit: str | None) -> list[float]:
    u = (unit or "").lower()
    if u == "%":
        return [tol / 100, tol]
    if u in ("bn", "billion"):
        return [tol * 1000, tol * 1e9]
    if u in ("tn", "trillion"):
        return [tol * 1e6, tol * 1e12]
    if u in ("m", "mn", "million"):
        return [tol, tol * 1e6]
    if u in ("k", "thousand"):
        return [tol / 1000, tol * 1000]
    if u in ("bp", "bps"):
        return [tol / 10000]
    return [tol, tol / 100]


def number_allowed(text_num: str, unit: str | None, allowed: list[float]) -> bool:
    num = float(text_num.replace(",", ""))
    if unit is None and float(num).is_integer() and (abs(num) <= 10 or 1990 <= num <= 2100):
        return True
    for cand, tol in zip(_candidates(num, unit), _scaled_tol(_tolerance(text_num, unit), unit)):
        for a in allowed:
            for sign in (1, -1):  # "fell 5%" may describe -0.05
                target = sign * a
                if abs(cand - target) <= max(tol, 0.005 * abs(target)) + 1e-12:
                    return True
    return False


def check_text(text: str, allowed: list[float], sources: str = "") -> GuardResult:
    """Check every sentence; return the offending numbers and a cleaned text without failing sentences."""
    src = re.sub(r"\s+", " ", sources).lower()
    bad_nums, bad_sents, keep = [], [], []
    for sentence in SENTENCE_RE.split(text.strip()) if text.strip() else []:
        work = sentence
        for q in QUOTE_RE.findall(sentence):
            if re.sub(r"\s+", " ", q).lower().strip() in src:
                work = work.replace(q, " ")
        work = LABEL_RE.sub(" ", work)
        bad_here = [m.group(0).strip() for m in NUM_RE.finditer(work)
                    if not number_allowed(m.group("num"), m.group("unit"), allowed)]
        if bad_here:
            bad_nums += bad_here
            bad_sents.append(sentence)
        else:
            keep.append(sentence)
    return GuardResult(not bad_nums, bad_nums, bad_sents, " ".join(keep))


def check_fields(data, allowed: list[float], sources: str = "", path: str = "") -> dict[str, GuardResult]:
    """Run the guard over every string field of a JSON-like structure. Keys ending in '_quote' are checked
    against the sources instead (the quote must appear verbatim)."""
    out = {}
    if isinstance(data, dict):
        for k, v in data.items():
            p = f"{path}.{k}" if path else k
            if isinstance(v, str) and (k == "quote" or k.endswith("_quote")):
                found = re.sub(r"\s+", " ", v).lower().strip() in re.sub(r"\s+", " ", sources).lower()
                out[p] = GuardResult(found or not v, [] if found or not v else ["quote not found in source"],
                                     [] if found or not v else [v], v if found else "")
            elif isinstance(v, str):
                out[p] = check_text(v, allowed, sources)
            else:
                out.update(check_fields(v, allowed, sources, p))
    elif isinstance(data, list):
        for i, v in enumerate(data):
            out.update(check_fields(v, allowed, sources, f"{path}[{i}]"))
    return out


def apply_cleaning(data, results: dict[str, GuardResult], path: str = ""):
    """Copy of `data` with failing sentences removed from each checked field."""
    if isinstance(data, dict):
        return {k: (results[f"{path}.{k}" if path else k].cleaned
                    if isinstance(v, str) and (f"{path}.{k}" if path else k) in results
                    else apply_cleaning(v, results, f"{path}.{k}" if path else k)) for k, v in data.items()}
    if isinstance(data, list):
        return [apply_cleaning(v, results, f"{path}[{i}]") for i, v in enumerate(data)]
    return data
