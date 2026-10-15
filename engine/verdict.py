"""Valuation verdict (rules, not AI), confidence and football field (pure). PROMPT.md section 5.

Fair value = weighted blend: scenario-weighted DCF 50%, comps 30%, historical multiples 20% (SOTP replaces
the DCF weight when it applies). Missing methods are dropped and the remaining weights rescaled, and the
report says so. Undervalued: price more than 15% below fair value; overvalued: more than 15% above.
"""
from __future__ import annotations

from dataclasses import dataclass, field

DEFAULT_WEIGHTS = {"dcf": 0.50, "comps": 0.30, "history": 0.20}
BAND = 0.15
UNDERVALUED, OVERVALUED, FAIR = "Undervalued", "Overvalued", "Fairly valued"


@dataclass
class Verdict:
    fair_value: float | None
    price: float
    gap: float | None                # price vs fair value: (fair value / price) - 1
    verdict: str | None
    weights_used: dict[str, float]
    components: dict[str, float | None]
    notes: list[str] = field(default_factory=list)
    confidence: str | None = None
    confidence_reasons: list[str] = field(default_factory=list)


def blend(components: dict[str, float | None], price: float, weights: dict[str, float] | None = None,
          sotp: float | None = None) -> Verdict:
    w = dict(weights or DEFAULT_WEIGHTS)
    comps = dict(components)
    notes = []
    if sotp is not None:
        comps["dcf"] = sotp
        notes.append("SOTP replaces the DCF in the blend (segments have materially different economics)")
    usable = {k: w[k] for k in w if comps.get(k) is not None and comps[k] > 0 and w[k] > 0}
    dropped = [k for k in w if k not in usable and w[k] > 0]
    if dropped:
        notes.append(f"not available: {', '.join(dropped)}; remaining weights rescaled")
    total = sum(usable.values())
    if total <= 0:
        return Verdict(None, price, None, None, {}, comps, notes + ["no valuation method available"])
    used = {k: v / total for k, v in usable.items()}
    fv = sum(used[k] * comps[k] for k in used)
    gap = fv / price - 1
    if price < fv * (1 - BAND):
        verdict = UNDERVALUED
    elif price > fv * (1 + BAND):
        verdict = OVERVALUED
    else:
        verdict = FAIR
    return Verdict(fv, price, gap, verdict, used, comps, notes)


def confidence(v: Verdict, *, estimate_dispersion: float | None, red_flags: int, amber_flags: int,
               tv_share: float | None, completeness: float, peers_meet_brief_filter: bool = True
               ) -> tuple[str, list[str]]:
    """High / Medium / Low from four signals; each weak signal costs a point (3 = High, 1-2 = Medium, <= 0 = Low)."""
    score, reasons = 3, []
    if estimate_dispersion is None:
        score -= 1
        reasons.append("no analyst consensus to anchor the forecast")
    elif estimate_dispersion > 0.15:
        score -= 1
        reasons.append(f"analyst revenue estimates are widely spread ({estimate_dispersion:.0%} high-low range)")
    if red_flags:
        score -= 2
        reasons.append(f"{red_flags} red flag(s)")
    if amber_flags >= 4:
        score -= 1
        reasons.append(f"{amber_flags} amber flags")
    if tv_share is not None and tv_share > 0.80:
        score -= 1
        reasons.append(f"terminal value is {tv_share:.0%} of enterprise value")
    if completeness < 0.75:
        score -= 1
        reasons.append(f"only {completeness:.0%} of key inputs available")
    if not peers_meet_brief_filter:
        score -= 1
        reasons.append("too few true peers: the peer filter had to be widened beyond same-industry, similar-size")
    if len(v.weights_used) < 3:
        reasons.append("fewer than three valuation methods in the blend")
        score -= 1
    level = "High" if score >= 3 else ("Medium" if score >= 1 else "Low")
    return level, reasons or ["consensus, data and methods all available with no warning signs"]


@dataclass
class Bar:
    method: str
    low: float | None
    high: float | None
    point: float | None
    note: str = ""


def football_field(*, dcf_bear: float | None, dcf_base: float | None, dcf_bull: float | None,
                   comps: dict, history: dict, analyst_targets: dict | None, week52: tuple[float, float] | None,
                   sotp: float | None = None) -> list[Bar]:
    bars = [Bar("DCF (bear-bull)", dcf_bear, dcf_bull, dcf_base, "scenario range")]
    if sotp is not None:
        bars.append(Bar("Sum of the parts", sotp, sotp, sotp))
    for m in comps.values():
        if m.implied_price is not None:
            bars.append(Bar(f"Comps {m.label}", m.implied_price_low, m.implied_price_high, m.implied_price,
                            "peer interquartile range"))
    for h in history.values():
        if h.implied_price is not None:
            bars.append(Bar(f"Own history {h.label}", h.implied_low, h.implied_high, h.implied_price,
                            "5-year low to high"))
    if analyst_targets and analyst_targets.get("low") and analyst_targets.get("high"):
        bars.append(Bar("Analyst price targets", analyst_targets["low"], analyst_targets["high"],
                        analyst_targets.get("median"), "low to high"))
    if week52:
        bars.append(Bar("52-week trading range", week52[0], week52[1], None))
    return bars
