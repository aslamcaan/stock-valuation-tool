"""One rating per report; the ADR ratio is applied and checked; margin and percentile labels say what they show."""
import dataclasses

import pytest

from data_desk import checks
from data_desk.adr import ADR_RATIOS, adr_ratio, is_foreign_private_issuer, on_file
from desks.rating_guard import drop_wrong_ratings
from engine.comps import implied_from_multiple
from engine.flags import AMBER, RED
from engine.values import percentile_label
from tests.engine_fixtures import engine_inputs


# --- 1. one rating -----------------------------------------------------------------------------------------------
def test_text_that_names_another_rating_is_dropped_and_logged():
    view = {"thesis": "Shares sit well above fair value. Hold, with a negative bias on price.",
            "reasoning_lines": ["Fair value is below the price, which caps the rating at Hold.",
                                "Free cash flow is negative.", "That supports Hold rather than Sell."],
            "notch_reason": "No reason to move the rating.", "conviction": "Low"}
    out, log = drop_wrong_ratings(view, "Sell", "MD")
    assert out["thesis"] == "Shares sit well above fair value."
    assert out["reasoning_lines"] == ["Free cash flow is negative."]  # a line naming another rating is removed
    assert out["conviction"] == "Low" and len(log) == 3 and all("rating is Sell" in x for x in log)


def test_text_naming_the_final_rating_is_kept_and_strong_variants_are_distinct():
    out, log = drop_wrong_ratings({"thesis": "A Buy on valuation. Not a Strong Buy."}, "Buy", "MD")
    assert out["thesis"] == "A Buy on valuation." and len(log) == 1
    out, log = drop_wrong_ratings({"thesis": "Sell-side analysts disagree; buy-side too. We sell nothing."}, "Hold", "MD")
    assert log == []  # 'Sell-side', 'buy-side' and the verb 'sell' are not ratings


def test_the_notch_explanation_may_name_the_rubric_rating_but_not_an_unrelated_one():
    view = {"notch_reason": "Rubric says Hold; moving down to Sell. Not a Buy.",
            "rating_vs_verdict_explanation": ""}
    out, log = drop_wrong_ratings(view, "Sell", "MD", {"notch_reason": {"Hold", "Sell"}})
    assert out["notch_reason"] == "Rubric says Hold; moving down to Sell." and len(log) == 1


# --- 3. ADR ratio ------------------------------------------------------------------------------------------------
def test_jumia_ads_is_two_ordinary_shares():
    assert ADR_RATIOS["JMIA"] == 2 and adr_ratio("jmia")[0] == 2 and on_file("JMIA")


def test_filer_type_comes_from_the_newest_periodic_form():
    assert is_foreign_private_issuer({"filings": {"recent": {"form": ["6-K", "20-F", "10-K"]}}})
    assert not is_foreign_private_issuer({"filings": {"recent": {"form": ["8-K", "10-Q", "20-F"]}}})
    assert not is_foreign_private_issuer({})


def test_a_missing_ratio_is_flagged_for_a_foreign_filer_when_it_cannot_be_checked():
    (f,) = checks.adr_ratio_status("XYZ", 1.0, False, True, None)
    assert f.code == "adr_ratio_unverified" and f.level == AMBER
    assert checks.adr_ratio_status("XYZ", 1.0, False, False, None) == []      # a 10-K filer: not an ADR
    assert checks.adr_ratio_status("XYZ", 1.0, False, True, 1.02) == []       # market cap confirms 1:1
    assert checks.adr_ratio_status("JMIA", 2.0, True, True, None) == []       # on file


def test_a_ratio_that_disagrees_with_the_market_cap_is_flagged():
    (f,) = checks.adr_ratio_status("JMIA", 1.0, False, True, 1.87)  # the Jumia run before the ratio was on file
    assert f.code == "adr_ratio_check" and "1.87" in f.message
    assert checks.adr_ratio_status("JMIA", 2.0, True, True, 1.87) == []  # 6.5% apart: within tolerance


def test_the_valuation_must_convert_per_share_values_with_the_companys_ratio():
    assert checks.adr_ratio_applied(2.0, 2.0) == []
    (f,) = checks.adr_ratio_applied(2.0, 1.0)
    assert f.code == "adr_ratio_not_applied" and f.level == RED


def test_the_ratio_reaches_every_per_us_share_value():
    from engine.valuation import value_company
    one = engine_inputs("KO")
    two = dataclasses.replace(one, adr_ratio=2.0)
    v1, v2 = value_company(one), value_company(two)
    assert v2.per_us_share_factor == 2.0 and checks.adr_ratio_applied(2.0, v2.per_us_share_factor) == []
    assert v1.per_us_share(10.0) == 10.0 and v2.per_us_share(10.0) == 20.0  # per ordinary share x ratio
    # the ratio also sets the market cap (price x shares / ratio), so the DCF itself moves a little (WACC weights)
    assert v2.per_us_share(v2.dcf.value_per_share) == pytest.approx(2 * v2.dcf.value_per_share)
    # peer multiples: implied price scales with the ratio too
    from types import SimpleNamespace
    comp = SimpleNamespace(net_income=5.0, revenue=100.0, ebitda=10.0, fcf=4.0)
    assert implied_from_multiple("ev_ebitda", 8.0, comp, 100.0, 50.0, 2.0) == \
        pytest.approx(2 * implied_from_multiple("ev_ebitda", 8.0, comp, 100.0, 50.0, 1.0))


# --- 2. labels ----------------------------------------------------------------------------------------------------
def test_percentiles_are_ordinals_not_percentages():
    assert [percentile_label(x) for x in (0.01, 0.02, 0.03, 0.11, 0.21, 0.9286)] == [
        "1st percentile", "2nd percentile", "3rd percentile", "11th percentile", "21st percentile", "93rd percentile"]
