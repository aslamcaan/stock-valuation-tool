"""Golden test 1b (test_grab_engine): run the engine with the user's own Grab assumptions and conventions.
Value per share must be within 1% of the model's (it should match exactly)."""
import json

import pytest

from engine.dcf import Conventions, DCFInputs, YearDrivers, run_dcf
from engine.values import MILLIONS, RATIO, Value
from engine.wacc import WaccInputs, compute_wacc
from tests.conftest import FIXTURES

M = json.loads((FIXTURES / "grab_expected.json").read_text(encoding="utf-8"))
A, H, C = M["assumptions"], M["historicals"], M["computed"]

# The user's conventions: end-of-year discounting, no stub, adjusted EBITDA basis with SBC ignored,
# explicit capex/D&A with no working capital, Gordon growth on the final-year FCF.
USER_CONVENTIONS = Conventions(discounting="end_year", stub=False, margin_basis="adjusted", sbc_as_cash=False,
                               reinvestment="explicit", terminal="gordon_final_fcf")


def v(x, name):
    return Value(x["value"], None, RATIO, "model", "user model", tag=x["cell"], note=name)


def user_wacc():
    bs, price = H["balance_sheet"], H["market"]["share_price"]["value"]
    mcap = Value(price * bs["shares_outstanding_m"]["value"], "USD", MILLIONS, "model", "user model",
                 note="price x shares (B26)")
    return compute_wacc(WaccInputs(
        risk_free=v(A["risk_free_rate"], "rf"), erp=v(A["equity_risk_premium"], "erp"),
        beta_regression=v(A["beta"], "beta"), unlevered_beta_industry=None,
        marginal_tax_rate=v(A["debt_tax_rate"], "tax"), crp=Value(0.0, None, RATIO, "model", "user model"),
        pre_tax_cost_of_debt=v(A["pre_tax_cost_of_debt"], "kd"), market_cap=mcap,
        debt=Value(bs["total_debt"]["value"], "USD", MILLIONS, "model", "user model"), beta_choice="regression"))


def user_inputs(wacc: float) -> DCFInputs:
    years = []
    for y in M["conventions"]["forecast_years"]:
        years.append(YearDrivers(
            label=y, revenue_growth=A["revenue_growth"][y]["value"],
            operating_margin=A["ebitda_margin"][y]["value"] - A["d_and_a_pct_revenue"][y]["value"],
            tax_rate=A["tax_rate"][y]["value"], da_pct=A["d_and_a_pct_revenue"][y]["value"],
            capex_pct=A["capex_pct_revenue"][y]["value"]))
    bs = H["balance_sheet"]
    return DCFInputs(base_label="FY2025A", base_revenue=H["FY2025A"]["revenue"]["value"], years=tuple(years),
                     wacc=wacc, terminal_growth=A["terminal_growth"]["value"], conventions=USER_CONVENTIONS,
                     bridge=(("cash and investments", bs["cash_and_investments"]["value"]),
                             ("total debt", -bs["total_debt"]["value"])),
                     shares=bs["shares_outstanding_m"]["value"])


def test_grab_engine_wacc_matches_model():
    w = user_wacc()
    assert w.cost_of_equity.value == pytest.approx(C["cost_of_equity"]["value"], rel=1e-12)
    assert w.wacc.value == pytest.approx(C["wacc"]["value"], rel=1e-12)


def test_grab_engine_value_per_share_within_1pct():
    r = run_dcf(user_inputs(user_wacc().wacc.value))
    model = C["value_per_share"]["value"]
    print(f"engine {r.value_per_share:.4f} vs model {model:.4f}")
    assert r.value_per_share == pytest.approx(model, rel=0.01)
    # it should in fact reproduce every line exactly
    assert r.value_per_share == pytest.approx(model, rel=1e-9)
    assert r.terminal_value == pytest.approx(C["terminal_value"]["value"], rel=1e-9)
    assert r.enterprise_value == pytest.approx(C["enterprise_value"]["value"], rel=1e-9)
    for row in r.years:
        assert row.fcf == pytest.approx(C["ufcf"][row.label]["value"], rel=1e-9)


def test_grab_engine_sensitivity_grid_matches_data_table():
    """The model's Excel data table (terminal growth x WACC) is reproduced by the engine."""
    s = M["sensitivity"]
    base = user_inputs(user_wacc().wacc.value)
    for gi, g in enumerate(s["terminal_growth"]):
        for wi, w in enumerate(s["wacc"]):
            from dataclasses import replace
            r = run_dcf(replace(base, wacc=w, terminal_growth=g))
            assert r.value_per_share == pytest.approx(s["value_per_share"][gi][wi], rel=1e-6), (g, w)
