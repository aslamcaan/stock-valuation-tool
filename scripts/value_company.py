"""Run the data desk and engine for tickers and print a valuation summary: python scripts/value_company.py KO"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.services import build_services  # noqa: E402
from data_desk.builder import build_company_data  # noqa: E402
from data_desk.valuation_inputs import build_engine_inputs  # noqa: E402
from engine.valuation import value_company  # noqa: E402


def pct(x):
    return "n/a" if x is None else f"{x:.1%}"


def summary(ticker: str, svc) -> None:
    cd = build_company_data(ticker, svc)
    ei, notes = build_engine_inputs(cd, svc)
    v = value_company(ei)
    w = v.wacc
    print(f"\n===== {cd.profile.name} ({ticker}) price ${ei.price.value:,.2f} ({ei.price.source})")
    print(f"Stage: {v.classification.stage_label} - {v.classification.stage_reason}")
    print(f"Industry: {ei.industry.name} ({ei.industry.how})")
    print(f"WACC {pct(w.wacc.value)} = Ke {pct(w.cost_of_equity.value)} (rf {pct(ei.risk_free.value)}, beta "
          f"{w.beta.value:.2f} [{w.beta.source}], ERP {pct(ei.erp.value)}, CRP {pct(ei.crp.value)}) | Kd after tax "
          f"{pct(w.after_tax_cost_of_debt.value)} ({v.cost_of_debt_detail['rating']}) | E/V {pct(w.weight_equity.value)}")
    print(f"  CRP: {ei.crp.note}")
    for name, d in v.plan.drivers.items():
        path = ", ".join(f"{x:.1%}" if name != "sales_to_capital" else f"{x:.2f}" for x in d.path)
        hist = "n/a" if d.history is None or d.history.value is None else (f"{d.history.value:.1%}" if name != "sales_to_capital" else f"{d.history.value:.2f}")
        cons = "n/a" if d.consensus is None else f"{d.consensus.value:.1%}"
        indu = "n/a" if d.industry is None else (f"{d.industry.value:.1%}" if name != "sales_to_capital" else f"{d.industry.value:.2f}")
        print(f"  {d.label:<18} hist {hist:>7} | cons {cons:>7} | industry {indu:>7} | [{d.confidence}] {d.source}")
        print(f"      path {v.plan.labels[0]}..: {path}")
    print(f"  Terminal growth {pct(v.plan.terminal_growth.value)}, terminal ROIC {pct(v.plan.terminal_roic.value)} "
          f"({v.plan.terminal_roic.note}); stub {v.plan.stub_fraction:.2f}; skipped {v.plan.skipped}")
    if v.dcf:
        d = v.dcf
        print(f"DCF: EV {d.enterprise_value:,.0f} (TV {d.tv_share_of_ev:.0%}) bridge "
              f"{sum(x for _, x in d.bridge):,.0f} -> equity {d.equity_value:,.0f} / {d.shares:,.1f}m sh = "
              f"${v.per_us_share(d.value_per_share):,.2f}")
        print("Scenarios: " + " | ".join(f"{s.scenario.name} ${v.per_us_share(s.value_per_share):,.2f} "
                                          f"({s.scenario.probability:.0%})" for s in v.scenarios)
              + f" -> weighted ${v.per_us_share(v.scenario_value):,.2f}")
        gap = v.per_us_share(v.scenario_value) / ei.price.value - 1
        verdict = "Undervalued" if gap > 0.15 else ("Overvalued" if gap < -0.15 / 1.15 else "Fairly valued")
        print(f"Provisional verdict (DCF only; comps and history added in Phase 5): {verdict} ({gap:+.1%})")
        rv = v.reverse or {}
        if rv.get("growth", {}).get("solved"):
            print(f"Reverse DCF (growth): price implies {rv['growth']['implied_cagr']:.1%} revenue CAGR over "
                  f"{rv['years']} years vs {rv['base_cagr']:.1%} in the base case")
        if rv.get("margin", {}).get("solved"):
            print(f"Reverse DCF (margin): price implies a {rv['margin']['implied_terminal_margin']:.1%} terminal "
                  f"operating margin vs {rv['margin']['base_terminal_margin']:.1%} in the base case")
        if v.structural_case:
            print(f"Structural case (current margin held): ${v.per_us_share(v.structural_case.value_per_share):,.2f}")
    print("Shares:", f"{v.diluted_shares.value:,.1f}m", v.diluted_shares.note or "")
    for f in v.flags:
        print("  FLAG", f.level, f.code, f.message[:150])
    for n in notes + v.plan.notes:
        print("  NOTE", n[:200])


if __name__ == "__main__":
    s = build_services()
    for t in sys.argv[1:]:
        summary(t.upper(), s)
