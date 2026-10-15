"""Rebuild EngineInputs offline from recorded fixtures (filings + market inputs)."""
import json
from datetime import date

from engine.analysis import analyse
from engine.forecast import ConsensusYear
from engine.valuation import EngineInputs, IndustryData
from engine.values import Value
from tests.conftest import FIXTURES, historicals_for


def _v(d):
    return None if d is None else Value(d["value"], d.get("currency"), d.get("unit") or "ratio", d.get("period") or "",
                                        d.get("source") or "fixture", note=d.get("note"))


def engine_inputs(ticker: str, overrides: dict | None = None) -> EngineInputs:
    f = json.loads((FIXTURES / f"engine_inputs_{ticker}.json").read_text(encoding="utf-8"))
    h = historicals_for(ticker)
    ind = f["industry"]
    cons = [ConsensusYear(date.fromisoformat(c["fiscal_year_end"]), c["revenue"], c["revenue_low"], c["revenue_high"],
                          c["ebit"], c["analysts"], c["source"], c.get("fetched_at")) for c in f["consensus"]]
    return EngineInputs(
        ticker=ticker, name=ticker, sic={"GRAB": "7389", "KO": "2080"}.get(ticker, ""),
        valuation_date=date.fromisoformat(f["valuation_date"]), historicals=h, analysis=analyse(h),
        price=_v(f["price"]), basic_shares=_v(f["basic_shares"]), adr_ratio=f["adr_ratio"],
        market_cap=_v(f["market_cap"]), risk_free=_v(f["risk_free"]), erp=_v(f["erp"]),
        beta_regression=_v(f["beta_regression"]),
        industry=IndustryData(ind["name"], ind["how"], _v(ind["unlevered_beta"]), _v(ind["operating_margin"]),
                              _v(ind["revenue_growth"]), _v(ind["sales_to_capital"])),
        crp=_v(f["crp"]), marginal_tax=_v(f["marginal_tax"]), rating_table_large=f["rating_table_large"],
        rating_table_small=f["rating_table_small"], consensus=cons, overrides=overrides or {})
