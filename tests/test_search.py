from datasources.search import label, search

ROWS = [
    {"cik": 1, "name": "Uber Technologies, Inc.", "ticker": "UBER", "exchange": "NYSE"},
    {"cik": 2, "name": "Grab Holdings Ltd", "ticker": "GRAB", "exchange": "Nasdaq"},
    {"cik": 3, "name": "Coca-Cola Co", "ticker": "KO", "exchange": "NYSE"},
    {"cik": 4, "name": "Coca-Cola Consolidated, Inc.", "ticker": "COKE", "exchange": "Nasdaq"},
    {"cik": 5, "name": "Grabby OTC Corp", "ticker": "GRBY", "exchange": "OTC"},
    {"cik": 6, "name": "Apple Inc.", "ticker": "AAPL", "exchange": "Nasdaq"},
    {"cik": 7, "name": "Pineapple Energy", "ticker": "PEGY", "exchange": "Nasdaq"},
]


def test_exact_ticker_first():
    assert search(ROWS, "ko")[0]["ticker"] == "KO"


def test_name_match_and_ordering():
    res = [r["ticker"] for r in search(ROWS, "coca")]
    assert res == ["KO", "COKE"] or res == ["COKE", "KO"]
    assert [r["ticker"] for r in search(ROWS, "apple")] == ["AAPL", "PEGY"]


def test_otc_excluded():
    assert [r["ticker"] for r in search(ROWS, "grab")] == ["GRAB"]


def test_empty_query_and_limit():
    assert search(ROWS, "  ") == []
    assert len(search(ROWS, "a", limit=2)) == 2


def test_label():
    assert label(ROWS[1]) == "Grab Holdings Ltd (GRAB) · Nasdaq"
