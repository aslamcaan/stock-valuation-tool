"""Company classification (pure): sector toolkit from SIC, lifecycle stage from the data, cycle position.

Stage rules (PROMPT.md 4b), applied in this order, with the evidence recorded:
1. Declining: revenue fell in each of the last 3 fiscal years.
2. Cyclical: cyclical SIC code (checked before growth, so a 175% revenue spike in memory chips is a cycle, not a
   start-up), or volatile revenue and margins while mostly profitable.
3. Early / pre-profit: revenue growth > 25% (latest, or 3-year CAGR with margin < 10%), or negative operating margin.
   A company with a positive operating margin and positive free cash flow is never pre-profit.
4. High growth, profitable: growth 15-25%, or faster growth from a company that is already profitable.
5. Mature growth: growth 5-15%.
6. Mature stable: growth < 5% with low margin volatility (otherwise mature growth).
Growth = 3-year revenue CAGR (the latest year is reported alongside). The review desk may override, with a reason.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from statistics import mean, median, pstdev

from engine.model import Historicals

CORPORATE, BANK, INSURER, REIT = "corporate", "bank", "insurer", "reit"
EARLY, HIGH_GROWTH, MATURE_GROWTH, MATURE_STABLE, CYCLICAL, DECLINING = (
    "early", "high_growth", "mature_growth", "mature_stable", "cyclical", "declining")
STAGE_LABELS = {EARLY: "Early / pre-profit", HIGH_GROWTH: "High growth, profitable", MATURE_GROWTH: "Mature growth",
                MATURE_STABLE: "Mature stable", CYCLICAL: "Cyclical", DECLINING: "Declining"}

# SIC codes treated as cyclical: mining and oil & gas, refining, chemicals, steel and metals, construction
# machinery, storage devices (e.g. SanDisk), semiconductors and memory, autos, shipping, airlines, homebuilders.
# A cyclical SIC alone is not enough: the company's own margins or growth must also be volatile.
CYCLICAL_SIC_RANGES = [(1000, 1499), (2800, 2829), (2860, 2869), (2900, 2999), (3310, 3399), (3523, 3537),
                       (3572, 3572), (3670, 3679), (3711, 3716), (4400, 4499), (4512, 4513), (1531, 1531)]
CYCLICAL_SIC_EXCLUDE: set[int] = set()
VOLATILE_MARGIN = 0.04   # 10-year standard deviation of operating margin
VOLATILE_GROWTH = 0.10   # 10-year standard deviation of revenue growth


@dataclass(frozen=True)
class Classification:
    toolkit: str
    toolkit_reason: str
    stage: str
    stage_reason: str
    evidence: dict = field(default_factory=dict)
    override: str | None = None  # set when the review desk overrides the stage

    @property
    def stage_label(self) -> str:
        return STAGE_LABELS[self.stage]


def toolkit_for_sic(sic: str) -> tuple[str, str]:
    try:
        code = int(sic)
    except (TypeError, ValueError):
        return CORPORATE, "no SIC code: corporate toolkit by default"
    if 6020 <= code <= 6039 or code in (6111, 6712):
        return BANK, f"SIC {code} is a bank / bank holding company: bank toolkit (no DCF)"
    if code == 6324:  # hospital & medical service plans (UNH, ELV, HUM, CNC): managed care, valued on operating profit
        return CORPORATE, (f"SIC {code} is managed care (health plans): valued like a services business on operating "
                           "profit (full DCF), not on book value")
    if 6300 <= code <= 6399:
        return INSURER, f"SIC {code} is an insurance carrier: insurance toolkit (no DCF)"
    if code == 6798:
        return REIT, f"SIC {code} is a real estate investment trust: REIT toolkit (no standard DCF)"
    return CORPORATE, f"SIC {code}: corporate toolkit (full DCF)"


def is_cyclical_sic(sic: str) -> bool:
    try:
        code = int(sic)
    except (TypeError, ValueError):
        return False
    return code not in CYCLICAL_SIC_EXCLUDE and any(lo <= code <= hi for lo, hi in CYCLICAL_SIC_RANGES)


def _series(h: Historicals, line: str) -> list[tuple[str, float]]:
    return [(p, h.v(line, p)) for p in h.fy_labels if h.v(line, p) is not None]


def margins(h: Historicals) -> list[tuple[str, float]]:
    out = []
    for p in h.fy_labels[-10:]:
        oi, rev = h.v("operating_income", p), h.v("revenue", p)
        if oi is not None and rev:
            out.append((p, oi / rev))
    return out


def cycle_position(h: Historicals, current_margin: float | None) -> dict:
    """Where the current operating margin sits in the company's own (up to) 10-year range."""
    ms = [m for _, m in margins(h)]
    if current_margin is None or len(ms) < 5:
        return {"available": False, "years": len(ms)}
    below = sum(1 for m in ms if m < current_margin)
    equal = sum(1 for m in ms if m == current_margin)
    pct = (below + 0.5 * equal) / len(ms)
    # the 90th percentile of the range by linear interpolation: a margin at a 5-year record is above it,
    # where a rank of (below + half the ties) / n would give exactly 0.90 and miss it
    s = sorted(ms)
    k = 0.9 * (len(s) - 1)
    p90 = s[int(k)] + (s[min(int(k) + 1, len(s) - 1)] - s[int(k)]) * (k - int(k))
    # mid-cycle target for a cyclical's margin path: half way between the typical year (the median, so one trough
    # year such as a -37% margin does not drag it down) and the 90th percentile
    cycle_target = (median(ms) + p90) / 2
    return {"available": True, "years": len(ms), "current_margin": current_margin, "percentile": pct,
            "p90_margin": p90, "mid_cycle_margin": mean(ms), "median_margin": median(ms),
            "cycle_target_margin": cycle_target, "min_margin": min(ms), "max_margin": max(ms),
            "margin_std": pstdev(ms), "volatile": pstdev(ms) > VOLATILE_MARGIN,
            "above_90th": current_margin >= p90 and current_margin > min(ms)}


def classify(h: Historicals, sic: str, current_margin: float | None = None) -> Classification:
    toolkit, toolkit_reason = toolkit_for_sic(sic)
    rev = _series(h, "revenue")
    fy = [p for p, _ in rev]
    growth = [(fy[i], rev[i][1] / rev[i - 1][1] - 1) for i in range(1, len(rev)) if rev[i - 1][1] > 0]
    latest_growth = growth[-1][1] if growth else None
    cagr3 = (rev[-1][1] / rev[-4][1]) ** (1 / 3) - 1 if len(rev) >= 4 and rev[-4][1] > 0 and rev[-1][1] > 0 else None
    g = cagr3 if cagr3 is not None else latest_growth
    ms = margins(h)
    margin_now = current_margin if current_margin is not None else (ms[-1][1] if ms else None)
    margin_std = pstdev([m for _, m in ms]) if len(ms) >= 3 else None
    growth_std = pstdev([x for _, x in growth[-10:]]) if len(growth) >= 3 else None
    profitable_share = (sum(1 for _, m in ms if m > 0) / len(ms)) if ms else 0.0
    fcf_p = h.ltm.label if h.ltm and h.v("fcf", h.ltm.label) is not None else (fy[-1] if fy else None)
    fcf_now = h.v("fcf", fcf_p) if fcf_p else None
    profitable_now = margin_now is not None and margin_now > 0 and fcf_now is not None and fcf_now > 0
    ev = {"revenue_cagr_3y": cagr3, "latest_revenue_growth": latest_growth, "operating_margin": margin_now,
          "margin_std": margin_std, "growth_std": growth_std, "profitable_year_share": profitable_share,
          "cyclical_sic": is_cyclical_sic(sic), "years_of_history": len(rev), "positive_fcf": fcf_now is not None and fcf_now > 0}

    def done(stage: str, reason: str) -> Classification:
        return Classification(toolkit, toolkit_reason, stage, reason, ev)

    if len(growth) >= 3 and all(x < 0 for _, x in growth[-3:]):
        return done(DECLINING, "revenue fell in each of the last three fiscal years ("
                    + ", ".join(f"{p} {x:+.1%}" for p, x in growth[-3:]) + ")")
    volatile = (growth_std is not None and margin_std is not None and growth_std > 0.15 and margin_std > 0.07
                and profitable_share >= 0.7 and (cagr3 is None or cagr3 < 0.25))
    sic_cycle_evidence = ((margin_std or 0) > VOLATILE_MARGIN or (growth_std or 0) > VOLATILE_GROWTH)
    short_history = len(ms) < 5  # too few years to show a cycle: the industry is the evidence
    if ev["cyclical_sic"] and (sic_cycle_evidence or short_history) and             (profitable_share >= 0.5 or (margin_now is not None and margin_now > 0)):
        span = (f"operating margin ranged {min(m for _, m in ms):.1%} to {max(m for _, m in ms):.1%} over {len(ms)} "
                f"years" if ms else "no operating margin history")
        return done(CYCLICAL, f"SIC {sic} is a cyclical industry; {span}"
                    + ("; with under five years of history the industry decides, not the company's own margins"
                       if short_history and not sic_cycle_evidence else ""))
    if volatile:
        return done(CYCLICAL, f"revenue growth volatility {growth_std:.1%} and margin volatility {margin_std:.1%} "
                    f"over {len(ms)} years while mostly profitable")
    if margin_now is not None and margin_now < 0:
        return done(EARLY, f"operating margin is negative ({margin_now:.1%})")
    if latest_growth is not None and latest_growth > 0.25 and not profitable_now:
        return done(EARLY, f"revenue grew {latest_growth:.1%} in the latest year (above 25%)")
    if cagr3 is not None and cagr3 > 0.25 and (margin_now is None or margin_now < 0.10) and not profitable_now:
        return done(EARLY, f"3-year revenue CAGR {cagr3:.1%} (above 25%) with a thin operating margin "
                    f"({margin_now:.1%})")
    if profitable_now and (g is not None and g > 0.25 or (latest_growth or 0) > 0.25):
        return done(HIGH_GROWTH, f"revenue growing fast (3-year CAGR {g:.1%}, latest year {latest_growth:.1%}) "
                    f"but already profitable: operating margin {margin_now:.1%} and positive free cash flow")
    if g is None:
        return done(MATURE_GROWTH, "insufficient history: mature growth assumed")
    if g >= 0.15:
        return done(HIGH_GROWTH, f"3-year revenue CAGR {g:.1%} (15-25%) with positive margins")
    if g >= 0.05:
        return done(MATURE_GROWTH, f"3-year revenue CAGR {g:.1%} (5-15%)")
    if margin_std is not None and margin_std <= 0.05:
        return done(MATURE_STABLE, f"3-year revenue CAGR {g:.1%} (below 5%) and operating margin volatility "
                    f"{margin_std:.1%} (low)")
    return done(MATURE_GROWTH, f"3-year revenue CAGR {g:.1%} (below 5%) but margin volatility "
                f"{margin_std:.1%} is too high for mature stable")
