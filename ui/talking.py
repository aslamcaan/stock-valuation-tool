"""Talking points: the figures for a worked example, read from one saved report (the same functions the report uses,
so the page never quotes a number the report does not show)."""
from __future__ import annotations

from pathlib import Path

from engine.classify import DECLINING
from engine.insights import peer_regressions, price_walk, value_split
from ui.format import money, mult, pct
from ui.insights import mc_cached, walk_args

CONVENTIONS = {"Today's margin held", "Own tax rate", "Today's ROIC held", "3% terminal growth",
               "Higher terminal growth"}


def example(rep) -> dict | None:
    """Headline, walk, value split, Monte Carlo and regression figures for a corporate-toolkit report; None for a
    bank, insurer or REIT, or a report without a DCF."""
    m = rep.model
    if m is None or getattr(m, "financial", None) is not None or m.valuation.dcf is None or m.valuation.dcf_inputs is None:
        return None
    v, vd = m.valuation, m.verdict
    f = v.per_us_share_factor
    price = vd.price / f  # per ordinary share, like the DCF
    out = {
        "ticker": rep.ticker, "name": rep.company.profile.name, "created_at": rep.created_at,
        "price": vd.price, "price_source": m.inputs.price.source, "price_date": m.inputs.price.period,
        "fair_value": vd.fair_value, "gap": vd.gap, "verdict": vd.verdict,
        "rating": getattr(rep.md, "rating", None), "conviction": getattr(rep.md, "conviction", None),
        "gate_note": getattr(rep.md, "gate_note", ""),
        "dcf": v.dcf.value_per_share * f, "wacc": v.wacc.wacc.value, "risk_free": m.inputs.risk_free.value,
        "stage": v.classification.stage_label, "tv_share": v.dcf.tv_share_of_ev,
        "weights": dict(getattr(vd, "weights_used", None) or {}),
    }
    steps = price_walk(v.dcf_inputs, price, *walk_args(rep))
    out["walk"] = [{**s, "value": s["value"] * f, "change": s["change"] * f} for s in steps]
    out["conventions"] = sum(s["change"] for s in out["walk"] if s["label"] in CONVENTIONS)
    rate = next((s for s in out["walk"] if s["label"] == "Discount rate the price needs"), None)
    out["rate_step"] = rate["change"] if rate else None
    out["implied_wacc_text"] = rate["detail"] if rate else None
    out["unexplained"] = next((s["change"] for s in out["walk"] if s["label"] == "Not explained"), None)

    sp = value_split(v.dcf, price)
    if sp and sp["market_ev"] > 0 and v.dcf.enterprise_value > 0:
        out["split"] = {"no_growth_ev": sp["no_growth_ev"], "growth_ours": sp["growth_ev"] / v.dcf.enterprise_value,
                        "growth_market": sp["market_growth_ev"] / sp["market_ev"]}
    cap = 0.0 if v.classification.stage == DECLINING else m.inputs.risk_free.value
    mc = mc_cached(v.dcf_inputs, price, cap)
    if mc:
        out["mc"] = {"p10": mc["pct"][10] * f, "p50": mc["pct"][50] * f, "p90": mc["pct"][90] * f,
                     "above": mc["prob_above_price"], "n": mc["valid"]}
    if m.comps and m.company_metrics is not None:
        br = sum(x.value for n, x in v.bridge if n != "Long-term investments")
        for r in peer_regressions(m.company_metrics, m.comps.peers, v.diluted_shares.value, br, f):
            if r["applicable"] and r["implied_price"] is not None:
                out.setdefault("regression", {**r, "median_price": m.comps.multiples[r["key"]].implied_price})
    return out


def pitch(x: dict) -> str:
    """The worked example in two or three sentences, every figure from `example`."""
    s = (f"On {x['ticker']} the tool's blended fair value is {money(x['fair_value'])} against a price of "
         f"{money(x['price'])}, so the verdict is {x['verdict']}" + (f" and the rating {x['rating']}" if x["rating"] else "")
         + f". The DCF alone gives {money(x['dcf'])} at a {pct(x['wacc'])} WACC.")
    s += " " + walk_sentence(x)
    return s


def walk_sentence(x: dict) -> str:
    """What the walk says, worded from the signs and sizes of its steps (never assumed)."""
    gap, conv, rate = x["price"] - x["dcf"], x["conventions"], x["rate_step"] or 0.0
    if abs(gap) < 0.005 * x["price"]:
        return "The DCF is within 0.5% of the price."
    parts = []
    if abs(conv) >= 0.005 * x["dcf"]:
        used = [w["label"][0].lower() + w["label"][1:] for w in x["walk"] if w["label"] in CONVENTIONS]
        parts.append(f"Common sell-side conventions ({', '.join(used)}) add {money(conv)} a share")
    elif gap > 0:
        parts.append("The sell-side conventions add almost nothing here")
    if rate:
        parts.append(f"the price then needs a {'lower' if rate > 0 else 'higher'} discount rate "
                     f"({x['implied_wacc_text']}), worth {money(abs(rate))}")
    out = "; ".join(parts) + "."
    if x["unexplained"]:
        out += f" {money(abs(x['unexplained']))} is left unexplained even then."
    if gap > 0 and rate < 0:
        out += " So on those conventions the price is below the DCF: the gap is about forecast conventions."
    elif gap > 0:
        out += (" So most of the gap is the required return, not the forecast." if rate > conv else
                " So most of the gap is forecast conventions, not the discount rate.")
    else:
        out += " The price is below our DCF."
    return out


def fmt_regression(r: dict) -> str:
    return (f"{r['label']} against {r['driver']}: R² {r['r2']:.2f} across {len(r['points'])} peers; warranted "
            f"{mult(r['warranted'])} implies {money(r['implied_price'])}, against {money(r['median_price'])} at the "
            "peer median" + (" (extrapolated beyond the peers' range)" if r["extrapolated"] else "") + ".")


def test_count(root: Path | None = None) -> int | None:
    """Number of test functions in tests/ (None when the folder is not deployed)."""
    root = root or Path(__file__).resolve().parent.parent / "tests"
    if not root.is_dir():
        return None
    return sum(line.lstrip().startswith("def test_") for p in root.glob("test_*.py")
               for line in p.read_text(encoding="utf-8").splitlines())
