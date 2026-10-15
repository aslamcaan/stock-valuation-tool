"""Record the market / reference inputs the engine used for a ticker, so engine tests run offline.

Run: python scripts/record_engine_inputs.py GRAB  -> tests/fixtures/engine_inputs_GRAB.json
"""
from __future__ import annotations

import json
import sys
from dataclasses import asdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.services import build_services  # noqa: E402
from data_desk.builder import build_company_data  # noqa: E402
from data_desk.valuation_inputs import build_engine_inputs  # noqa: E402


def v(x):
    return None if x is None else {"value": x.value, "source": x.source, "period": x.period, "note": x.note,
                                   "unit": x.unit, "currency": x.currency}


def main(ticker: str) -> None:
    svc = build_services()
    cd = build_company_data(ticker, svc)
    ei, notes = build_engine_inputs(cd, svc)
    out = {
        "ticker": ticker, "recorded": date.today().isoformat(), "valuation_date": ei.valuation_date.isoformat(),
        "price": v(ei.price), "basic_shares": v(ei.basic_shares), "adr_ratio": ei.adr_ratio,
        "market_cap": v(ei.market_cap), "risk_free": v(ei.risk_free), "erp": v(ei.erp),
        "beta_regression": v(ei.beta_regression),
        "industry": {"name": ei.industry.name, "how": ei.industry.how,
                     "unlevered_beta": v(ei.industry.unlevered_beta), "operating_margin": v(ei.industry.operating_margin),
                     "revenue_growth": v(ei.industry.revenue_growth), "sales_to_capital": v(ei.industry.sales_to_capital)},
        "crp": v(ei.crp), "marginal_tax": v(ei.marginal_tax),
        "rating_table_large": ei.rating_table_large, "rating_table_small": ei.rating_table_small,
        "consensus": [{**asdict(c), "fiscal_year_end": c.fiscal_year_end.isoformat()} for c in ei.consensus],
        "notes": notes,
    }
    path = ROOT / "tests" / "fixtures" / f"engine_inputs_{ticker}.json"
    path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print("wrote", path)


if __name__ == "__main__":
    for t in sys.argv[1:]:
        main(t.upper())
