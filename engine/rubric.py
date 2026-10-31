"""MD rating rubric (pure). Code scores four criteria deterministically; the MD (AI) scores five with cited
evidence. Code maps the weighted score to a rating; the MD may move it one notch with a written reason.
"""
from __future__ import annotations

from dataclasses import dataclass

RATINGS = ["Strong Sell", "Sell", "Hold", "Buy", "Strong Buy"]
WEIGHTS = {
    # code-scored
    "valuation_gap": 0.25, "business_quality": 0.15, "financial_strength": 0.10, "estimate_revisions": 0.05,
    # AI-scored
    "moat": 0.15, "management": 0.10, "governance": 0.05, "industry": 0.10, "catalysts": 0.05,
}
LABELS = {"valuation_gap": "Valuation gap", "business_quality": "Business quality", "financial_strength":
          "Financial strength", "estimate_revisions": "Estimate revisions", "moat": "Competitive position and moat",
          "management": "Management and capital allocation", "governance": "Governance", "industry": "Industry outlook",
          "catalysts": "Catalysts and news flow"}
AI_CRITERIA = ["moat", "management", "governance", "industry", "catalysts"]
CODE_CRITERIA = ["valuation_gap", "business_quality", "financial_strength", "estimate_revisions"]


@dataclass
class Score:
    criterion: str
    score: int          # 1-5
    evidence: str
    by: str             # "code" or "MD"


def _band(x: float, cuts: list[float]) -> int:
    """1-5 from ascending cut points (4 cuts)."""
    return 1 + sum(1 for c in cuts if x >= c)


def score_valuation_gap(gap: float | None) -> Score:
    if gap is None:
        return Score("valuation_gap", 3, "no fair value: neutral score", "code")
    s = _band(gap, [-0.30, -0.15, 0.15, 0.30])
    return Score("valuation_gap", s, f"fair value is {gap:+.1%} versus the price", "code")


def score_business_quality(roic: float | None, wacc: float | None, margin_pct: float | None) -> Score:
    parts, scores = [], []
    if roic is not None and wacc is not None:
        spread = roic - wacc
        scores.append(_band(spread, [-0.10, -0.03, 0.03, 0.10]))
        parts.append(f"ROIC {roic:.1%} vs WACC {wacc:.1%} ({spread * 100:+.1f} points)")
    if margin_pct is not None:
        scores.append(_band(margin_pct, [0.2, 0.4, 0.6, 0.8]))
        parts.append(f"operating margin at the {margin_pct:.0%} percentile of peers")
    if not scores:
        return Score("business_quality", 3, "insufficient data: neutral score", "code")
    return Score("business_quality", round(sum(scores) / len(scores)), "; ".join(parts), "code")


def score_financial_strength(net_debt: float | None, ebitda: float | None, interest_cover: float | None) -> Score:
    if net_debt is None:
        return Score("financial_strength", 3, "net debt unavailable: neutral score", "code")
    if net_debt <= 0:
        return Score("financial_strength", 5, f"net cash of {-net_debt:,.0f}m", "code")
    if not ebitda or ebitda <= 0:
        return Score("financial_strength", 1, f"net debt {net_debt:,.0f}m with no positive EBITDA", "code")
    lev = net_debt / ebitda
    s = 6 - _band(lev, [1.0, 2.5, 4.0, 6.0])
    ev = f"net debt / EBITDA {lev:.1f}x"
    if interest_cover is not None and interest_cover < 3 and s > 1:
        s -= 1
        ev += f"; interest cover only {interest_cover:.1f}x"
    return Score("financial_strength", max(1, s), ev, "code")


def score_revisions(revisions: dict) -> Score:
    for days in (90, 60, 30):
        r = revisions.get(days, {})
        if r.get("available") and r.get("changes"):
            first = next(iter(r["changes"].values()))
            x = first.get("eps") if first.get("eps") is not None else first.get("revenue")
            if x is not None:
                return Score("estimate_revisions", _band(x, [-0.05, -0.01, 0.01, 0.05]),
                             f"consensus moved {x:+.1%} over {days} days", "code")
    return Score("estimate_revisions", 3, "no revision history yet: neutral score", "code")


RATING_CUTS = [(4.2, "Strong Buy"), (3.4, "Buy"), (2.6, "Hold"), (1.8, "Sell")]  # weighted score at or above


def rating_from(scores: list[Score]) -> tuple[float, str]:
    total = sum(WEIGHTS[s.criterion] * s.score for s in scores)
    weight = sum(WEIGHTS[s.criterion] for s in scores)
    avg = total / weight if weight else 3.0
    r = next((name for cut, name in RATING_CUTS if avg >= cut), "Strong Sell")
    return avg, r


def apply_notch(rating: str, notch: int) -> str:
    """The MD may move the code rating by at most one notch."""
    notch = max(-1, min(1, int(notch)))
    i = RATINGS.index(rating) + notch
    return RATINGS[max(0, min(len(RATINGS) - 1, i))]


def gate_by_verdict(rating: str, verdict: str | None) -> tuple[str, str]:
    """The rating may not point against the valuation: an Overvalued verdict caps it at Hold and an Undervalued one
    floors it at Hold (quality and the MD's notch move it only within that). Returns (rating, note or "")."""
    if verdict == "Overvalued" and RATINGS.index(rating) > RATINGS.index("Hold"):
        return "Hold", f"{rating} capped at Hold: the valuation verdict is Overvalued"
    if verdict == "Undervalued" and RATINGS.index(rating) < RATINGS.index("Hold"):
        return "Hold", f"{rating} raised to Hold: the valuation verdict is Undervalued"
    return rating, ""


def conflicts_with_verdict(rating: str, verdict: str | None) -> bool:
    return (rating in ("Buy", "Strong Buy") and verdict == "Overvalued") or \
           (rating in ("Sell", "Strong Sell") and verdict == "Undervalued")


def score_financial_quality(normalised_return: float | None, coe: float | None, label: str) -> Score:
    """Banks and insurers: normalised return on (tangible) equity against the cost of equity."""
    if normalised_return is None or coe is None:
        return Score("business_quality", 3, "insufficient data: neutral score", "code")
    spread = normalised_return - coe
    return Score("business_quality", _band(spread, [-0.06, -0.02, 0.02, 0.06]),
                 f"normalised {label} {normalised_return:.1%} vs cost of equity {coe:.1%} "
                 f"({spread * 100:+.1f} points)", "code")


def score_financial_strength_sector(toolkit: str, cet1: float | None = None, combined_ratio: float | None = None,
                                    debt_to_ebitda: float | None = None) -> Score:
    """Banks: CET1 ratio. Insurers: combined ratio (underwriting profit funds capital). REITs: debt / EBITDA."""
    if toolkit == "bank" and cet1 is not None:
        return Score("financial_strength", _band(cet1, [0.08, 0.10, 0.115, 0.13]), f"CET1 ratio {cet1:.1%}", "code")
    if toolkit == "insurer" and combined_ratio is not None:
        return Score("financial_strength", 6 - _band(combined_ratio, [0.90, 0.95, 1.00, 1.05]),
                     f"combined ratio {combined_ratio:.1%}", "code")
    if toolkit == "reit" and debt_to_ebitda is not None:
        return Score("financial_strength", 6 - _band(debt_to_ebitda, [4.0, 5.5, 7.0, 8.5]),
                     f"debt / EBITDA {debt_to_ebitda:.1f}x", "code")
    return Score("financial_strength", 3, "capital measure unavailable: neutral score", "code")
