"""Live API smoke tests. Run with: pytest -m live  (needs .env keys)."""
import pytest

from core.services import build_services

pytestmark = pytest.mark.live


@pytest.fixture(scope="module")
def svc():
    return build_services()


def test_sec_tickers_and_companyfacts(svc):
    cik = svc.edgar.cik_for("AAPL")
    assert cik == 320193
    facts = svc.edgar.companyfacts(cik).payload
    assert "us-gaap" in facts["facts"]


def test_sec_foreign_filer_ifrs(svc):
    cik = svc.edgar.cik_for("GRAB")
    assert "ifrs-full" in svc.edgar.companyfacts(cik).payload["facts"]


def test_fred_dgs10(svc):
    _, v, _ = svc.fred.latest("DGS10")
    assert 0 < v < 15


def test_fmp_quote(svc):
    q = svc.fmp.call("quote", "AAPL", force=True).payload
    assert q and q[0]["price"] > 0


def test_damodaran_live(svc):
    assert 0.02 < svc.damodaran.implied_erp().value < 0.08
