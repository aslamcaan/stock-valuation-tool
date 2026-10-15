"""Full Modelling-desk summary: python scripts/report_summary.py KO GRAB"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.services import build_services  # noqa: E402
from data_desk.builder import build_company_data  # noqa: E402
from desks.modelling import run_modelling  # noqa: E402


def money(x):
    return "n/a" if x is None else f"${x:,.2f}"


def main(ticker, svc):
    cd = build_company_data(ticker, svc)
    r = run_modelling(cd, svc)
    v, vd = r.valuation, r.verdict
    print(f"\n===== {cd.profile.name} ({ticker}) price {money(vd.price)} | stage {v.classification.stage_label}")
    print(f"Fair value {money(vd.fair_value)} ({vd.gap:+.1%}) -> {vd.verdict}, confidence {vd.confidence}"
          if vd.fair_value else "no fair value")
    print("  components:", {k: money(x) for k, x in vd.components.items()}, "weights:",
          {k: f"{w:.0%}" for k, w in vd.weights_used.items()}, "|", "; ".join(vd.notes))
    print("  confidence reasons:", "; ".join(vd.confidence_reasons))
    if r.comps:
        print("  peers:", ", ".join(f"{p.ticker} ({p.market_cap/1e3:,.0f}bn)" for p in r.comps.peers))
        print("  selection:", " | ".join(r.comps.selection_steps))
        for m in r.comps.multiples.values():
            print(f"   {m.label:<13} peer median {m.median and round(m.median,1)} (n={len(m.peer_values)}) own "
                  f"{m.company_value and round(m.company_value,1)} -> implied {money(m.implied_price)}")
        for k, b in r.comps.benchmarks.items():
            pct = "n/a" if b["percentile"] is None else f"{b['percentile']:.0%}"
            print(f"   bench {b['label']:<18} company {b['company'] if b['company'] is None else round(b['company'],3)}"
                  f" peer median {b['peer_median'] if b['peer_median'] is None else round(b['peer_median'],3)} pct {pct}")
    for h in r.history.values():
        print(f"   history {h.label:<13} range {h.low and round(h.low,1)}-{h.high and round(h.high,1)} median "
              f"{h.median and round(h.median,1)} now {h.current and round(h.current,1)} -> implied {money(h.implied_price)}")
    print("  revisions:", {d: (x.get('snapshot_date') if x['available'] else x.get('reason')) for d, x in r.revisions.items()})
    print("  football:", "; ".join(f"{b.method} {money(b.low)}-{money(b.high)}" for b in r.football))
    print("  flags:", [f"{f.level}:{f.code}" for f in r.flags])
    for n in r.notes[:8]:
        print("  note:", n)


if __name__ == "__main__":
    s = build_services()
    for t in sys.argv[1:]:
        main(t.upper(), s)
