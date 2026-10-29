"""Forensic scores (pure Python): Beneish M-score (earnings manipulation risk) and Altman Z-score (distress risk).

Both use reported statement lines only, each traced to its tag and period. Where an input is missing the score says
so: a missing ratio that has a neutral value (1.0) is set to it and listed; a missing core input means no score.
Neither model was built for banks or insurers, so financials (SIC 6000-6799) get no score, with the reason.

Beneish (1999), 8 variables, comparing a fiscal year with the one before:
  M = -4.84 + 0.920 DSRI + 0.528 GMI + 0.404 AQI + 0.892 SGI + 0.115 DEPI - 0.172 SGAI + 4.679 TATA - 0.327 LVGI
  M above -1.78 suggests a higher likelihood of earnings manipulation.
Altman: the original Z (1968) for public manufacturers (SIC 2000-3999), otherwise Z'' (1995, non-manufacturers;
the plain form, without the +3.25 emerging-market constant), which leaves out sales/assets and uses book equity.
Both run on the reporting-currency statements: every term is a same-currency ratio, so FX moves cannot distort them.
  Z   = 1.2 X1 + 1.4 X2 + 3.3 X3 + 0.6 X4 + 1.0 X5     safe > 2.99, distress < 1.81
  Z'' = 6.56 X1 + 3.26 X2 + 6.72 X3 + 1.05 X4          safe > 2.60, distress < 1.10
  X1 working capital / assets, X2 retained earnings / assets, X3 EBIT / assets, X4 equity (market value for Z, book
  for Z'') / total liabilities, X5 sales / assets.
"""
from __future__ import annotations

from dataclasses import dataclass, field

BENEISH_COEF = {"DSRI": 0.920, "GMI": 0.528, "AQI": 0.404, "SGI": 0.892, "DEPI": 0.115, "SGAI": -0.172,
                "TATA": 4.679, "LVGI": -0.327}
BENEISH_CONST = -4.84
BENEISH_THRESHOLD = -1.78
NEUTRAL = {"GMI", "AQI", "DEPI", "SGAI", "LVGI"}  # ratios with a neutral value of 1.0 when an input is missing
Z_ORIGINAL = {"X1": 1.2, "X2": 1.4, "X3": 3.3, "X4": 0.6, "X5": 1.0}
Z_DOUBLE_PRIME = {"X1": 6.56, "X2": 3.26, "X3": 6.72, "X4": 1.05}
ZONES = {"Z": (1.81, 2.99), "Z''": (1.10, 2.60)}


@dataclass
class ForensicScore:
    name: str
    period: str
    value: float | None
    reading: str                                   # plain-English zone
    components: dict[str, float] = field(default_factory=dict)
    inputs: list[dict] = field(default_factory=list)   # {line, period, value, source}
    notes: list[str] = field(default_factory=list)
    model: str = ""
    figures: dict[str, float] = field(default_factory=dict)  # numbers quoted in the reading and notes (for the AI)


def is_financial(sic: str | None) -> bool:
    try:
        return 6000 <= int(sic or "") <= 6799
    except ValueError:
        return False


def is_manufacturer(sic: str | None) -> bool:
    try:
        return 2000 <= int(sic or "") <= 3999
    except ValueError:
        return False


class _Reader:
    """Reads lines from Historicals and records each input with its source, for the trace."""

    def __init__(self, h):
        self.h, self.inputs = h, []

    def __call__(self, line: str, period: str) -> float | None:
        v = self.h.get(line, period)
        if v is None or v.value is None:
            return None
        self.inputs.append({"line": line, "period": period, "value": v.value,
                            "source": f"{v.source}{' (' + v.tag + ')' if getattr(v, 'tag', None) else ''}"})
        return v.value


def _div(a, b):
    return None if a is None or b in (None, 0) else a / b


def beneish(h, sic: str | None, year: str, prior: str) -> ForensicScore:
    """M-score for fiscal year `year` against `prior` (labels from h.fy_labels)."""
    s = ForensicScore("Beneish M-score", year, None, "", model="8-variable (Beneish 1999)")
    if is_financial(sic):
        s.reading = "not meaningful for banks and insurers"
        return s
    g = _Reader(h)
    t, p = {}, {}
    for d, per in ((t, year), (p, prior)):
        for line in ("revenue", "receivables", "cost_of_revenue", "gross_profit", "current_assets", "ppe_net",
                     "total_assets", "d_and_a", "sga", "current_liabilities", "long_term_debt", "net_income", "cfo"):
            d[line] = g(line, per)
        if d["cost_of_revenue"] is None and d["gross_profit"] is not None and d["revenue"] is not None:
            d["cost_of_revenue"] = d["revenue"] - d["gross_profit"]
    s.inputs = g.inputs
    core = [("revenue", t), ("revenue", p), ("receivables", t), ("receivables", p), ("total_assets", t),
            ("total_assets", p), ("net_income", t), ("cfo", t)]
    missing = [f"{k} ({year if d is t else prior})" for k, d in core if d[k] is None]
    if missing:
        s.reading = "not computed: missing " + ", ".join(missing)
        return s
    if t["revenue"] <= 0 or p["revenue"] <= 0:
        s.reading = "not computed: revenue is zero or negative"
        return s

    def gm(d):
        return _div(d["revenue"] - d["cost_of_revenue"], d["revenue"]) if d["cost_of_revenue"] is not None else None

    def soft(d):  # share of assets that is neither current nor PP&E
        return None if d["current_assets"] is None or d["ppe_net"] is None else \
            1 - (d["current_assets"] + d["ppe_net"]) / d["total_assets"]

    def dep(d):
        return None if d["d_and_a"] is None or d["ppe_net"] is None else _div(d["d_and_a"], d["d_and_a"] + d["ppe_net"])

    both_ltd = t["long_term_debt"] is not None and p["long_term_debt"] is not None

    def lev(d):  # long-term debt only when both years report it, so the two years are like for like
        return None if d["current_liabilities"] is None else \
            (d["current_liabilities"] + (d["long_term_debt"] if both_ltd else 0.0)) / d["total_assets"]

    c = {
        "DSRI": _div(t["receivables"] / t["revenue"], p["receivables"] / p["revenue"]),
        "GMI": _div(gm(p), gm(t)),
        "AQI": _div(soft(t), soft(p)),
        "SGI": t["revenue"] / p["revenue"],
        "DEPI": _div(dep(p), dep(t)),
        "SGAI": _div(_div(t["sga"], t["revenue"]), _div(p["sga"], p["revenue"])),
        "LVGI": _div(lev(t), lev(p)),
        "TATA": (t["net_income"] - t["cfo"]) / t["total_assets"],
    }
    for k in list(c):
        if c[k] is None:
            if k in NEUTRAL:
                c[k] = 1.0
                s.notes.append(f"{k} set to the neutral 1.0: an input is missing or zero")
            else:
                s.reading = f"not computed: {k} could not be calculated"
                return s
    if not both_ltd:
        s.notes.append("LVGI uses current liabilities only: long-term debt not reported in both years")
    s.components = c
    s.value = BENEISH_CONST + sum(BENEISH_COEF[k] * v for k, v in c.items())
    s.reading = ("above -1.78: higher likelihood of earnings manipulation; check accruals and receivables"
                 if s.value > BENEISH_THRESHOLD else "below -1.78: no sign of earnings manipulation")
    s.figures = {"threshold": BENEISH_THRESHOLD}
    if s.notes:
        s.reading += " (partial: see notes)"
    return s


def altman(h, sic: str | None, period: str, market_cap: float | None, market_cap_source: str = "market data"
           ) -> ForensicScore:
    """Z (manufacturers, market value of equity) or Z'' (others, book equity) at `period`.
    `market_cap` must be in the same currency and unit as `h` (millions)."""
    manuf = is_manufacturer(sic)
    name = "Z" if manuf else "Z''"
    s = ForensicScore(f"Altman {name}-score", period, None, "",
                      model="original Z (1968), public manufacturers" if manuf else
                      "Z'' (1995), non-manufacturers")
    if is_financial(sic):
        s.reading = "not meaningful for banks and insurers"
        return s
    g = _Reader(h)
    ta, ca, cl = g("total_assets", period), g("current_assets", period), g("current_liabilities", period)
    re_, ebit, tl = g("retained_earnings", period), g("operating_income", period), g("total_liabilities", period)
    sales = g("revenue", period) if manuf else None
    eq = market_cap if manuf else (g("parent_equity", period) if g.h.get("total_equity", period) is None
                                   else g("total_equity", period))
    if manuf and market_cap is not None:
        g.inputs.append({"line": "market_cap", "period": "current", "value": market_cap,
                         "source": market_cap_source})
    s.inputs = g.inputs
    need = {"total assets": ta, "current assets": ca, "current liabilities": cl, "retained earnings": re_,
            "operating income (EBIT)": ebit, "total liabilities": tl,
            ("market value of equity" if manuf else "book equity"): eq}
    if manuf:
        need["revenue"] = sales
    missing = [k for k, v in need.items() if v is None]
    if missing:
        s.reading = "not computed: missing " + ", ".join(missing)
        return s
    if ta <= 0 or tl <= 0:
        s.reading = "not computed: total assets or liabilities not positive"
        return s
    x = {"X1": (ca - cl) / ta, "X2": re_ / ta, "X3": ebit / ta, "X4": eq / tl}
    if manuf:
        x["X5"] = sales / ta
    coef = Z_ORIGINAL if manuf else Z_DOUBLE_PRIME
    s.components = x
    s.value = sum(coef[k] * v for k, v in x.items())
    lo, hi = ZONES[name]
    s.figures = {"distress_below": lo, "safe_above": hi}
    s.reading = (f"safe zone (above {hi:.2f})" if s.value > hi else
                 f"distress zone (below {lo:.2f}): elevated risk of financial distress" if s.value < lo else
                 f"grey zone ({lo:.2f}-{hi:.2f})")
    # An accumulated deficit from past losses (common after years of growth spending) can drag the score down
    # even when the company holds net cash; say so rather than let the zone stand alone.
    terms = {k: coef[k] * v for k, v in x.items()}
    others = sum(v for k, v in terms.items() if k != "X2")
    net_debt = g("net_debt", period)
    s.inputs = g.inputs
    if s.value <= hi and terms["X2"] < 0 and others > lo and net_debt is not None and net_debt < 0:
        s.figures.update({"retained_earnings_m": round(re_), "score_without_x2": round(others, 2),
                          "net_cash_m": round(-net_debt)})
        s.notes.append(f"The score is pulled down by the accumulated deficit (retained earnings {re_:,.0f}m); "
                       f"without that term it would be {others:.2f}, and the company has net cash of "
                       f"{-net_debt:,.0f}m. Read the zone with care.")
    return s


def forensic_scores(h, sic: str | None, market_cap: float | None, market_cap_source: str = "market data"
                    ) -> dict[str, list[ForensicScore]]:
    """Scores for every fiscal year with a prior year (Beneish) and every fiscal year (Altman), oldest first.
    Altman's market-value term uses today's market cap, so only the latest year gets the original Z's X4 from
    market data; earlier years are shown only for Z'' (book equity)."""
    labels = list(h.fy_labels)
    out = {"beneish": [beneish(h, sic, y, p) for p, y in zip(labels, labels[1:])]}
    if is_manufacturer(sic):
        out["altman"] = [altman(h, sic, labels[-1], market_cap, market_cap_source)] if labels else []
    else:
        out["altman"] = [altman(h, sic, y, None) for y in labels]
    return out
