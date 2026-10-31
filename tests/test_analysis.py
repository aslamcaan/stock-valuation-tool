"""Financial analysis on Uber, checked against hand calculations from the reported figures."""

import pytest

from engine.analysis import analyse
from tests.conftest import historicals_for


@pytest.fixture(scope="module")
def uber():
    h = historicals_for("UBER")
    return h, analyse(h, [{"eps_actual": 1.0, "eps_estimate": 0.8}, {"eps_actual": 0.5, "eps_estimate": 0.6}])


def test_margins_and_growth(uber):
    h, a = uber
    assert a.m("operating_margin", "FY2025") == pytest.approx(5565 / 52017)
    assert a.m("revenue_growth", "FY2025") == pytest.approx(52017 / 43978 - 1)
    assert a.cagr["revenue_cagr_3y"].value == pytest.approx((52017 / h.v("revenue", "FY2022")) ** (1 / 3) - 1)


def test_returns(uber):
    h, a = uber
    pe24, pe25 = h.v("parent_equity", "FY2024"), h.v("parent_equity", "FY2025")
    assert a.m("roe", "FY2025") == pytest.approx(10053 / ((pe24 + pe25) / 2))
    # Uber's FY2025 effective tax rate is negative (valuation allowance release) -> statutory 21% used
    etr = a.metrics["effective_tax_rate"]["FY2025"]
    assert etr.value == 0.21 and "statutory" in etr.note
    assert a.m("nopat", "FY2025") == pytest.approx(5565 * 0.79)
    roe = a.m("roe", "FY2025")
    dupont = a.m("net_margin", "FY2025") * a.m("asset_turnover", "FY2025") * a.m("equity_multiplier", "FY2025")
    assert dupont == pytest.approx(roe)


def test_quality_and_working_capital(uber):
    h, a = uber
    assert a.m("sbc_pct_revenue", "FY2025") == pytest.approx(h.v("sbc", "FY2025") / 52017)
    assert a.m("fcf_conversion", "FY2025") == pytest.approx((10099 - 336) / 10053)
    assert a.m("dso", "FY2025") == pytest.approx(h.v("receivables", "FY2025") / 52017 * 365)


def test_track_record(uber):
    _, a = uber
    assert a.track_record["quarters"] == 2 and a.track_record["eps_beats"] == 1


def test_every_metric_is_traceable(uber):
    _, a = uber
    for metric, by_period in a.metrics.items():
        for v in by_period.values():
            assert v.formula or v.source in ("assumption",), metric
            assert v.trace()


def test_commentary_uses_computed_figures(uber):
    _, a = uber
    text = " ".join(s for section in a.commentary.values() for s in section)
    assert f"{a.m('revenue_growth', 'FY2025') * 100:.1f}%" in text
    assert f"{a.m('operating_margin', 'FY2025') * 100:.1f}%" in text
    assert "4,488m" in text  # FY2025 net income minus operating income (10,053 - 5,565)


def test_track_record_uses_the_last_three_years_only(uber):
    """KO, 2026-10-31: FMP returned 136 quarters and the report said 'beat in 86 of the last 136 quarters'."""
    h, _ = uber
    hist = [{"date": f"{1990 + q // 4}-{3 * (q % 4) + 3:02d}-30", "eps_actual": 1.0, "eps_estimate": 2.0 if q < 100 else 0.5}
            for q in range(136)]
    tr = analyse(h, hist).track_record
    assert tr["quarters"] == 12 and tr["eps_beats"] == 12  # only the newest 12 (all beats) count
    assert tr["rows"][0]["date"] > tr["rows"][-1]["date"]
