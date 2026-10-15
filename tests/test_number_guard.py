"""Golden test 11: generated text with an invented number is caught and fixed or dropped."""
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
