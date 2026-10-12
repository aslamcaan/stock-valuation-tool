"""Offline tests for the EDGAR, FMP, FRED and Damodaran clients (HTTP is faked)."""
import json

import pytest

from core.http import DataSourceError
from datasources import damodaran as dam
from datasources.damodaran import DamodaranClient
from datasources.edgar import EdgarClient
from datasources.fmp import ENDPOINTS, FmpClient
from datasources.fred import FredClient
from tests.conftest import FIXTURES, FakeResponse

SUBMISSIONS = {
    "name": "Test Co", "sic": "7372",
    "filings": {"recent": {
        "form": ["10-Q", "10-K", "8-K", "10-K"],
        "accessionNumber": ["0001-25-000003", "0001-25-000002", "0001-25-000004", "0001-24-000001"],
        "filingDate": ["2025-05-01", "2025-02-01", "2025-06-01", "2024-02-01"],
        "reportDate": ["2025-03-31", "2024-12-31", "2025-06-01", "2023-12-31"],
        "primaryDocument": ["q.htm", "k.htm", "e.htm", "k23.htm"],
        "primaryDocDescription": ["", "", "", ""],
    }, "files": []},
}


# --- EDGAR ----------------------------------------------------------------------------
def test_edgar_requires_user_agent(cache):
    with pytest.raises(DataSourceError, match="SEC_USER"):
        EdgarClient(cache, "").submissions(1)


def test_edgar_sends_user_agent_and_parses_tickers(cache, fake_get):
    calls, responses = fake_get
    responses.append(FakeResponse({"fields": ["cik", "name", "ticker", "exchange"],
                                   "data": [[320193, "Apple Inc.", "AAPL", "Nasdaq"]]}))
    client = EdgarClient(cache, "Jane Doe jane@example.com")
    assert client.cik_for("aapl") == 320193
    assert calls[0]["headers"]["User-Agent"] == "Jane Doe jane@example.com"
    assert client.cik_for("AAPL") == 320193 and len(calls) == 1  # second lookup from cache


def test_edgar_filings_filtered_and_sorted(cache, fake_get):
    _, responses = fake_get
    responses.append(FakeResponse(SUBMISSIONS))
    client = EdgarClient(cache, "Jane Doe jane@example.com")
    ks = client.filings(42, forms={"10-K"})
    assert [f.filing_date for f in ks] == ["2025-02-01", "2024-02-01"]
    assert ks[0].url(42) == "https://www.sec.gov/Archives/edgar/data/42/000125000002/k.htm"


def test_companyfacts_url_zero_padded(cache, fake_get):
    calls, responses = fake_get
    responses.append(FakeResponse({"facts": {}}))
    EdgarClient(cache, "J j@x.com").companyfacts(320193)
    assert calls[0]["url"].endswith("CIK0000320193.json")


# --- FMP -------------------------------------------------------------------------------
def test_fmp_key_sent_but_not_cached(cache, fake_get, tmp_path):
    calls, responses = fake_get
    responses.append(FakeResponse([{"symbol": "AAPL", "price": 1.0}]))
    FmpClient(cache, "SECRETKEY").call("quote", "aapl")
    assert calls[0]["params"]["apikey"] == "SECRETKEY" and calls[0]["params"]["symbol"] == "AAPL"
    for f in cache.root.rglob("*"):
        if f.is_file():
            assert "SECRETKEY" not in f.read_text(encoding="utf-8", errors="ignore")


def test_fmp_error_message_payload_raises(cache, fake_get):
    _, responses = fake_get
    responses.append(FakeResponse({"Error Message": "Restricted Endpoint"}))
    with pytest.raises(DataSourceError, match="Restricted"):
        FmpClient(cache, "K").call("peers", "AAPL")


def test_fmp_missing_key(cache):
    with pytest.raises(DataSourceError, match="FMP_API_KEY"):
        FmpClient(cache, "").call("quote", "AAPL")


def test_fmp_probe_classifies(cache, fake_get):
    _, responses = fake_get

    def respond(url, params):
        if "stock-peers" in url:
            return FakeResponse(status=402, text="Restricted Endpoint", url=url)
        if "news" in url:
            return FakeResponse([], url=url)
        return FakeResponse([{"x": 1}], url=url)

    responses.append(respond)
    rows = FmpClient(cache, "K").probe(symbols=("AAPL",))
    by = {r["endpoint"]: r["status"] for r in rows}
    assert by["peers"] == "unavailable" and by["news"] == "empty" and by["quote"] == "ok"
    assert set(by) == set(ENDPOINTS)


# --- FRED ------------------------------------------------------------------------------
def test_fred_missing_values_become_none(cache, fake_get):
    calls, responses = fake_get
    responses.append(FakeResponse({"observations": [{"date": "2025-01-02", "value": "4.5"},
                                                    {"date": "2025-01-03", "value": "."}]}))
    fred = FredClient(cache, "FREDKEY")
    d, v, _ = fred.latest("DGS10")
    assert (d, v) == ("2025-01-02", 4.5)
    assert calls[0]["params"]["api_key"] == "FREDKEY"


# --- Damodaran (recorded files) ----------------------------------------------------------
@pytest.fixture
def damodaran(cache):
    from core.http import cache_key
    for name, fname in [("erp", "ERPbymonth.xlsx"), ("country", "ctryprem.xlsx"),
                        ("betas_us", "betas.xls"), ("margins_us", "margin.xls")]:
        cache.write("damodaran", cache_key(dam.BASE + dam.FILES[name]),
                    (FIXTURES / "damodaran" / fname).read_bytes(), binary=True)
    return DamodaranClient(cache)


def test_damodaran_erp(damodaran):
    erp = damodaran.implied_erp()
    assert 0.02 < erp.value < 0.08 and erp.as_of[:4].isdigit()


def test_damodaran_country_risk(damodaran):
    table, as_of, _ = damodaran.country_risk()
    assert table["United States"]["crp"] < 0.01
    assert table["Indonesia"]["crp"] > table["Singapore"]["crp"]
    regions, _ = damodaran.regional_crp()
    assert regions["Africa"] > regions["Western Europe"] > 0


def test_damodaran_betas_and_margins(damodaran):
    betas, _, _ = damodaran.industry_betas("us")
    assert 0.3 < betas["Beverage (Soft)"]["unlevered_beta"] < 1.5
    assert "Total Market" in betas
    margins, _, _ = damodaran.industry_margins("us")
    assert 0 < margins["Beverage (Soft)"]["operating_margin"] < 0.5
