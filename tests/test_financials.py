"""Financial-sector toolkits (pure engine): formulas checked by hand."""
from datetime import date
from types import SimpleNamespace

import pytest

from engine.classify import BANK, INSURER, REIT
from engine.financials import (FinancialError, FinInputs, ddm, justified_multiple, residual_income,
                               returns_on_book, value_financial)
from engine.model import Historicals, Period
from engine.values import PER_SHARE, RATIO, Value


def hist(**lines_by_period) -> Historicals:
    labels = sorted({p for d in lines_by_period.values() for p in d})
    periods = [Period(lab, date(int(lab[2:]), 12, 31), None, "FY") for lab in labels]
    lines = {k: {p: Value(v, "USD", PER_SHARE if k == "dps_declared" else "m", p, "test") for p, v in d.items()}
             for k, d in lines_by_period.items()}
    return Historicals("USD", "us-gaap", periods, lines)


def r(x):
    return Value(x, None, RATIO, "current", "test")


def test_justified_multiple():
    # (ROTE - g) / (CoE - g): (15% - 3%) / (10% - 3%) = 1.714x
    assert justified_multiple(0.15, 0.10, 0.03) == pytest.approx(0.12 / 0.07)
    with pytest.raises(FinancialError):
        justified_multiple(0.15, 0.03, 0.03)


def test_residual_income_equals_justified_when_returns_are_constant():
    """With a constant return (no fade, all excess kept), RI = B x (ROE - g)/(CoE - g) when book grows at g."""
    coe, g, roe = 0.10, 0.03, 0.15
    retention = g / roe  # book grows exactly at g
    out = residual_income(100.0, roe, roe, coe, g, retention, years=10, fade=1, kept=1.0)
    assert out["value"] == pytest.approx(100 * justified_multiple(roe, coe, g), rel=1e-9)


def test_residual_income_first_year_by_hand():
    out = residual_income(50.0, 0.12, 0.12, 0.10, 0.02, 0.5, years=10, fade=1, kept=1.0)
    y1 = out["rows"][0]
    assert y1["residual_income"] == pytest.approx((0.12 - 0.10) * 50.0)
    assert out["rows"][1]["opening_book"] == pytest.approx(50.0 * (1 + 0.12 * 0.5))


def test_ddm_two_stage_by_hand():
    d = ddm(2.0, 0.05, 0.02, 0.09, years=2)
    d1, d2 = 2.0 * 1.05, 2.0 * 1.05 ** 2
    tv = d2 * 1.02 / (0.09 - 0.02)
    assert d["value"] == pytest.approx(d1 / 1.09 + d2 / 1.09 ** 2 + tv / 1.09 ** 2)


def _bank_hist():
    years = ["FY2021", "FY2022", "FY2023", "FY2024", "FY2025"]
    eq = {y: 1000 + 60 * k for k, y in enumerate(years)}
    return hist(parent_equity=eq, goodwill={y: 100 for y in years}, intangibles={y: 0 for y in years},
                net_income_common={y: 120 for y in years}, net_income_attributable={y: 125 for y in years},
                total_assets={y: 12000 for y in years}, net_interest_income={y: 300 for y in years},
                noninterest_income={y: 200 for y in years}, noninterest_expense={y: 300 for y in years},
                loans_gross={y: 7000 for y in years}, deposits={y: 9000 for y in years},
                net_charge_offs={y: 35 for y in years}, dps_declared={y: 0.4 for y in years},
                shares_outstanding={y: 100 for y in years})


def _inputs(h, toolkit=BANK, reported=None, peers=(), **ov):
    return FinInputs(toolkit, h, Value(30.0, "USD", PER_SHARE, "current", "test"),
                     Value(100.0, None, "shares_m", "FY2025", "test"), 1.0, r(0.04), r(0.05), r(0.0),
                     Value(1.1, None, "x", "current", "test"), reported or {}, list(peers), ov)


def test_bank_metrics_and_methods():
    h = _bank_hist()
    fv = value_financial(_inputs(h))
    m = {x.key: x for x in fv.metrics}
    tce25, tce24 = 1240 - 100, 1180 - 100
    assert m["rote"].value.value == pytest.approx(120 / ((tce25 + tce24) / 2))
    assert m["efficiency_ratio"].value.value == pytest.approx(300 / 500)
    assert m["loan_to_deposit"].value.value == pytest.approx(7000 / 9000)
    assert m["tbvps"].value.value == pytest.approx(tce25 / 100)
    assert m["nco_rate"].value.value == pytest.approx(35 / 7000)
    assert fv.cost_of_equity.value == pytest.approx(0.04 + 1.1 * 0.05)
    # growth capped at risk-free - 0.5 points
    assert fv.growth.value == pytest.approx(0.03)  # min(sustainable, risk-free - 0.5 points, 3%)
    j = fv.detail["justified"]
    assert fv.methods["justified"].value == pytest.approx(j["multiple"] * tce25 / 100)
    assert {"justified", "residual_income", "ddm"} <= set(fv.methods)
    assert "comps_pe" not in fv.methods  # fewer than three peers


def test_reported_book_value_is_used_and_flagged_when_it_differs():
    h = _bank_hist()
    rep = {"tbvps": Value(12.50, "USD", PER_SHARE, "FY2025", "10-K text")}
    fv = value_financial(_inputs(h, reported=rep))
    assert fv.base_per_share.value == 12.50
    assert any(f.code == "book_vs_reported" for f in fv.flags)


def test_peer_comps_need_three_peers():
    h = _bank_hist()
    peers = [SimpleNamespace(ticker=t, name=t, period="FY2025", market_cap=mc, tangible_equity=te,
                             common_equity=te, net_income_common=ni, net_income=ni, pe_meaningful=True)
             for t, mc, te, ni in (("A", 1500, 1000, 120), ("B", 2000, 1000, 150), ("C", 1200, 1000, 100))]
    fv = value_financial(_inputs(h, peers=peers))
    assert fv.detail["comps_pb"]["median"] == pytest.approx(1.5)
    assert fv.methods["comps_pb"].value == pytest.approx(1.5 * 11.40)
    assert fv.detail["comps_pe"]["median"] == pytest.approx(12.5)


def test_hard_stop_when_cost_of_equity_not_above_growth():
    h = _bank_hist()
    with pytest.raises(FinancialError, match="Hard stop"):
        value_financial(_inputs(h, cost_of_equity=0.03, long_run_growth=0.03))


def test_returns_on_book_uses_average_tangible_equity():
    h = _bank_hist()
    rets = returns_on_book(h, BANK)
    assert set(rets) == {"FY2022", "FY2023", "FY2024", "FY2025"}
    assert rets["FY2022"].value == pytest.approx(120 / ((960 + 900) / 2))


def test_insurer_uses_book_value_and_reported_combined_ratio():
    years = ["FY2023", "FY2024", "FY2025"]
    h = hist(parent_equity={y: 2000 for y in years}, net_income_common={y: 250 for y in years},
             premiums_earned={"FY2024": 4000, "FY2025": 4400}, losses_incurred={"FY2025": 2700},
             shares_outstanding={y: 100 for y in years}, dps_declared={y: 4.0 for y in years},
             total_assets={y: 15000 for y in years})
    rep = {"combined_ratio": Value(0.899, None, RATIO, "FY2025", "10-K text")}
    fv = value_financial(_inputs(h, INSURER, reported=rep))
    m = {x.key: x for x in fv.metrics}
    assert m["combined_ratio"].reported.value == 0.899
    assert m["loss_ratio"].value.value == pytest.approx(2700 / 4400)
    assert m["premium_growth"].value.value == pytest.approx(0.10)
    assert fv.base_per_share.value == pytest.approx(20.0)


def test_reit_ffo_and_nav():
    years = ["FY2024", "FY2025"]
    h = hist(net_income_common={y: 1000 for y in years}, d_and_a={y: 2500 for y in years},
             real_estate_impairment={"FY2025": 470}, real_estate_gains={"FY2025": 180},
             net_income={y: 1000 for y in years}, interest_expense={y: 900 for y in years},
             total_debt={y: 28000 for y in years},
             cash_and_investments={y: 500 for y in years}, shares_diluted_weighted={y: 900 for y in years},
             shares_outstanding={y: 930 for y in years}, dps_declared={y: 3.2 for y in years},
             )
    peers = [SimpleNamespace(ticker=t, name=t, period="FY2025", market_cap=mc, ev=ev, noi=noi, ffo=f)
             for t, mc, ev, noi, f in (("A", 9000, 15000, 1000, 600), ("B", 9000, 14000, 1000, 700),
                                       ("C", 9000, 12500, 1000, 500))]
    fv = value_financial(_inputs(h, REIT, peers=peers))
    m = {x.key: x for x in fv.metrics}
    assert m["ffo"].value.value == pytest.approx(1000 + 2500 + 470 - 180)
    cap = 1000 / 14000  # median NOI / EV
    noi = 1000 + 900 + 2500 + 470 - 180  # EBITDAre
    assert fv.methods["nav"].value == pytest.approx((noi / cap - (28000 - 500)) / 100)
    assert fv.detail["comps_pffo"]["median"] == pytest.approx(15.0)


def test_retention_counts_buybacks():
    """Book grows only by what is neither paid out nor bought back."""
    from engine.financials import total_payout
    h = _bank_hist()
    for y in h.fy_labels:
        h.lines.setdefault("dividends_paid", {})[y] = Value(-40.0, "USD", "m", y, "test")
        h.lines.setdefault("buybacks", {})[y] = Value(-60.0, "USD", "m", y, "test")
    assert total_payout(h).value == pytest.approx(100 / 125)
    fv = value_financial(_inputs(h))
    assert fv.detail["residual_income"]["retention"] == pytest.approx(1 - 100 / 125)
