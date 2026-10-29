"""Golden test 11: generated text with an invented number is caught and fixed or dropped."""
import pytest
from desks.number_guard import apply_cleaning, check_fields, check_text, flatten_numbers

RESULTS = {"operating_income": 1110.0, "revenue_growth": 0.183, "wacc": 0.0865, "value_per_share": 5.39,
           "ev_ebitda": 13.4, "nested": [{"x": 52017.0}]}
ALLOWED = flatten_numbers(RESULTS)


def test_matching_with_units_and_rounding():
    assert check_text("Operating income was $1.1bn in FY2023.", ALLOWED).ok
    assert check_text("Revenue grew 18.3% while WACC is 8.65%.", ALLOWED).ok
    assert check_text("We value the shares at $5.39, or 13.4x EBITDA.", ALLOWED).ok
    assert check_text("Revenue reached 52,017m.", ALLOWED).ok
    assert check_text("Revenue reached $52.0bn.", ALLOWED).ok


def test_invented_number_caught():
    r = check_text("Operating income was $1.1bn. Margins will reach 35% by 2030.", ALLOWED)
    assert not r.ok and r.bad_numbers == ["35%"]
    assert r.cleaned == "Operating income was $1.1bn."


def test_years_labels_and_small_counts_exempt():
    assert check_text("In FY2025 and Q3 2026 the company beat in 3 of 4 quarters.", ALLOWED).ok


def test_quotes_must_come_from_source():
    src = "Gross Bookings grew 21% year-over-year to $193.5 billion."
    assert check_text('Management said "Gross Bookings grew 21% year-over-year to $193.5 billion".', ALLOWED, src).ok
    assert not check_text('Management said "Gross Bookings grew 40% year-over-year".', ALLOWED, src).ok


def test_fields_checked_and_cleaned():
    data = {"thesis": "Revenue grew 18.3%. Fair value is $9.99.", "risks": [{"text": "WACC of 8.65% looks low."}],
            "evidence_quote": "not in the filing"}
    res = check_fields(data, ALLOWED, sources="some filing text")
    assert not res["thesis"].ok and res["risks[0].text"].ok and not res["evidence_quote"].ok
    cleaned = apply_cleaning(data, res)
    assert cleaned["thesis"] == "Revenue grew 18.3%." and cleaned["evidence_quote"] == ""


def test_verified_research_figures_allowed():
    from desks.number_guard import numbers_from_text
    allowed = ALLOWED + numbers_from_text("Gross Bookings $193,454 million; MAPCs 202 million; tax benefit $5.0 billion")
    assert check_text("Gross Bookings reached $193,454 million and MAPCs 202 million.", allowed).ok
    assert check_text("A $5.0bn tax benefit inflated earnings.", allowed).ok
    assert not check_text("Gross Bookings reached $210,000 million.", allowed).ok


# --- holes found in the Release 2 sweep ----------------------------------------------------------------------------
def test_small_numbers_with_a_currency_sign_or_decimal_are_checked():
    from desks.number_guard import check_text
    assert not check_text("Our fair value is $9 per share.", [2.4]).ok
    assert not check_text("Fair value 9.0 per share.", [2.4]).ok
    assert check_text("Three of 5 peers agree.", [2.4]).ok  # bare small counts stay exempt


def test_comma_amounts_are_not_years():
    from desks.number_guard import check_text
    assert not check_text("Debt is $2,050m.", [1000.0]).ok
    assert check_text("By 2030 margins converge.", [0.1]).ok


def test_direction_must_match_the_sign():
    from desks.number_guard import check_text
    assert not check_text("The stock trades 12% above fair value.", [-0.12]).ok
    assert check_text("Fair value is 12% below the price.", [-0.12]).ok
    assert check_text("Revenue fell 5%.", [-0.05]).ok
    assert check_text("Revenue grew 5%.", [0.05]).ok


def test_other_currency_amounts_must_be_quoted_from_sources():
    from desks.number_guard import check_text
    assert not check_text("Revenue was €1.1bn.", [1110.0]).ok
    assert check_text("Revenue was €1.1bn.", [1110.0], sources="Net sales were €1.1bn in the year.").ok
    assert check_text("Revenue was $1.1bn.", [1110.0]).ok


@pytest.mark.parametrize("text,allowed", [
    ("The company has net cash of $5.0bn.", [-5000.0]),
    ("Free cash flow was -$200m.", [-200.0]),
    ("Free cash flow was −$200m.", [-200.0]),
    ("EPS was $(1.20).", [-1.2]),
    ("Growth of 10-15% is assumed.", [0.10, 0.15]),
    ("It burned $200m of cash.", [-200.0]),
])
def test_signed_amounts_written_naturally_pass(text, allowed):
    assert check_text(text, allowed).ok


def test_rule_thresholds_only_in_sentences_about_a_limit():
    assert not check_text("Revenue grew 15% last year.", [0.1234], contextual=[0.15]).ok
    assert check_text("WACC sits outside the 6-15% range.", [0.1234], contextual=[0.06, 0.15]).ok


def test_ratio_does_not_let_a_hundredfold_percentage_through():
    assert check_text("The stock moved 0.48% on the day.", [0.0048]).ok
    assert not check_text("The stock moved 48% on the day.", [0.0048]).ok


def test_currency_codes_need_the_figure_verbatim_in_sources():
    assert not check_text("Sales were EUR 1.2bn.", []).ok
    assert check_text("Sales were EUR 1.2bn.", [], sources="... sales were EUR 1.2bn in 2025 ...").ok
