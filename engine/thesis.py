"""Thesis and exit conditions (pure). The user saves a thesis and up to five 'what proves me wrong' conditions per
holding. A check marks each as holding, at risk or broken, or says there is no evidence. Code, not the AI, decides
what counts: a status other than 'holding' needs a dated, sourced piece of evidence or it is downgraded."""
from __future__ import annotations

MAX_CONDITIONS = 5
MAX_LENGTH = 300
STATUSES = ("holding", "at_risk", "broken", "no_evidence")
LABEL = {"holding": "Holding", "at_risk": "At risk", "broken": "Broken", "no_evidence": "No evidence yet"}
SEVERITY = {"broken": 3, "at_risk": 2, "no_evidence": 1, "holding": 0}


def clean_conditions(raw: list[str]) -> list[str]:
    """Trim, drop blanks and duplicates, keep at most five. Raises ValueError if one is too long."""
    out: list[str] = []
    for c in raw:
        c = " ".join((c or "").split())
        if not c or c.lower() in (x.lower() for x in out):
            continue
        if len(c) > MAX_LENGTH:
            raise ValueError(f"A condition can be at most {MAX_LENGTH} characters (this one is {len(c)}).")
        out.append(c)
    if len(out) > MAX_CONDITIONS:
        raise ValueError(f"At most {MAX_CONDITIONS} conditions per holding (you gave {len(out)}).")
    return out


def enforce(results: list[dict], n_conditions: int) -> list[dict]:
    """One result per condition, in order. Anything the AI left out, mislabelled or could not source becomes
    'no evidence'; 'at risk' and 'broken' keep their status only with a source and a date."""
    by_index = {r.get("index"): r for r in results if isinstance(r.get("index"), int)}
    out = []
    for i in range(n_conditions):
        r = dict(by_index.get(i) or {})
        status = r.get("status") if r.get("status") in STATUSES else "no_evidence"
        if status in ("at_risk", "broken") and not (r.get("source") and r.get("date") and r.get("evidence")):
            r["reason"] = ((r.get("reason") or "") + " (Downgraded: no dated, sourced evidence was given.)").strip()
            status = "no_evidence"
        if not r:
            r = {"reason": "The check returned nothing for this condition."}
        r.update(index=i, status=status, label=LABEL[status])
        out.append(r)
    return out


def overall(results: list[dict]) -> str | None:
    return max((r["status"] for r in results), key=lambda s: SEVERITY[s]) if results else None
