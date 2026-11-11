"""Valuation verdict (rules, not AI), confidence and football field (pure). PROMPT.md section 5.

Fair value = weighted blend: scenario-weighted DCF 50%, comps 30%, historical multiples 20% (SOTP replaces
the DCF weight when it applies). Missing methods are dropped and the remaining weights rescaled, and the
report says so. Undervalued: price more than 15% below fair value; overvalued: more than 15% above.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace

DEFAULT_WEIGHTS = {"dcf": 0.50, "comps": 0.30, "history": 0.20}
BAND = 0.15
MAX_COMPONENT_SPREAD = 3.0  # methods further apart than this (highest / lowest) cannot be blended into one number
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
    # set when the headline is the scenario-weighted DCF instead of the blend, and why (printed at the top of the report)
    headline_note: str = ""
    fallback: str | None = None            # "components_diverge" or "review_desk"
    blend_fair_value: float | None = None  # the blend that was not used for the verdict
    top_notes: list[str] = field(default_factory=list)  # other plain-English lines printed at the top of the report
    dcf_value: float | None = None         # the scenario-weighted DCF per US share, always (the fallback headline)
    dcf_is_sotp: bool = False              # the "dcf" component is the sum of the parts, which replaced the DCF


def _band_verdict(fair_value: float, price: float) -> str:
    if price < fair_value * (1 - BAND):
        return UNDERVALUED
    if price > fair_value * (1 + BAND):
        return OVERVALUED
    return FAIR


def fall_back_to_dcf(v: Verdict, dcf_value: float | None, reason: str, kind: str) -> Verdict:
    """Stop using the blend for the verdict: the headline becomes the scenario-weighted DCF, confidence is Low and the
    reason is printed at the top. Without a usable DCF the blend stands, but the note and Low confidence still say it
    should not be relied on."""
    if dcf_value is None or dcf_value <= 0 or not v.price:
        return replace(v, headline_note=f"{reason} No usable DCF to fall back on, so the blended figure stands, but do "
                       "not rely on it.", fallback=kind, confidence="Low",
                       confidence_reasons=[reason] + [r for r in v.confidence_reasons if r != reason])
    return replace(v, fair_value=dcf_value, gap=dcf_value / v.price - 1, verdict=_band_verdict(dcf_value, v.price),
                   weights_used={"dcf": 1.0}, dcf_value=dcf_value, headline_note=f"{reason} The headline is the scenario-weighted DCF "
                   f"(${dcf_value:,.2f}) instead of the blend" + (f" (${v.fair_value:,.2f})." if v.fair_value else "."),
                   fallback=kind, blend_fair_value=v.blend_fair_value or v.fair_value, confidence="Low",
                   confidence_reasons=[reason] + [r for r in v.confidence_reasons if r != reason],
                   notes=v.notes + [f"verdict from the scenario-weighted DCF alone: {reason}"])


def blend(components: dict[str, float | None], price: float, weights: dict[str, float] | None = None,
          sotp: float | None = None, dcf_value: float | None = None) -> Verdict:
    """`dcf_value` is the scenario-weighted DCF per US share. It is what the headline falls back to, and what a sum of
    the parts is checked against: a SOTP more than 3x from the DCF is left out, not blended in as if it were the DCF."""
    w = dict(weights or DEFAULT_WEIGHTS)
    comps = dict(components)
    notes = []
    dcf_value = dcf_value if dcf_value is not None else comps.get("dcf")
    is_sotp = False
    if sotp is not None and dcf_value is not None and dcf_value > 0 and sotp > 0 and             max(sotp, dcf_value) / min(sotp, dcf_value) > MAX_COMPONENT_SPREAD:
        notes.append(f"sum of the parts (${sotp:,.2f}) left out: more than {MAX_COMPONENT_SPREAD:g}x from the DCF "
                     f"(${dcf_value:,.2f})")
        sotp = None
    if sotp is not None:
        comps["dcf"] = sotp
        is_sotp = True
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
    out = Verdict(fv, price, gap, _band_verdict(fv, price), used, comps, notes, dcf_value=dcf_value,
                  dcf_is_sotp=is_sotp)
    vals = [comps[k] for k in used]
    if len(vals) >= 2 and max(vals) / min(vals) > MAX_COMPONENT_SPREAD:
        spread = max(vals) / min(vals)
        listed = ", ".join(f"{'sum of the parts' if k == 'dcf' and is_sotp else k} ${comps[k]:,.2f}" for k in used)
        return fall_back_to_dcf(out, dcf_value, f"The valuation methods disagree by {spread:.1f}x ({listed}), "
                                f"more than the {MAX_COMPONENT_SPREAD:g}x limit for blending them.", "components_diverge")
    return out


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
        score -= 3
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
    if v.fallback:  # the headline is not the plain blend: never better than Low
        level = "Low"
        reasons = [r for r in [v.headline_note.split(" The headline")[0]] if r] + reasons
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
