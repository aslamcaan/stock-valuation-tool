"""End-to-end Data desk run, offline: SEC responses come from recorded fixtures via the cache.

Market data is not cached here, so the run must degrade gracefully (flags, no crash).
"""
from datetime import date

import pytest

from core.cache import Cache
from core.config import Settings
from core.http import cache_key
from core.services import build_services
from data_desk.builder import DataDeskError, build_company_data
from datasources.edgar import COMPANYFACTS_URL, SUBMISSIONS_URL, TICKERS_URL
from tests.conftest import load_edgar_fixture

TICKERS = ["UBER", "GRAB", "AAPL"]


@pytest.fixture(scope="module")
def svc(tmp_path_factory):
    root = tmp_path_factory.mktemp("cache")
    cache = Cache(root)
    rows = []
    for t in TICKERS:
        d = load_edgar_fixture(t)
        rows.append(d["tickers_row"])
        cache.write("companyfacts", cache_key(COMPANYFACTS_URL.format(cik=d["cik"])), d["companyfacts"])
        cache.write("filings", cache_key(SUBMISSIONS_URL.format(cik=d["cik"])), d["submissions"])
    cache.write("reference", cache_key(TICKERS_URL), rows)
    return build_services(Settings(sec_user_name="Test", sec_user_email="t@example.com", cache_dir=root, offline=True))


def test_uber_offline(svc):
    steps = []
    cd = build_company_data("UBER", svc, today=date(2026, 10, 14), progress=steps.append)
    assert cd.profile.name.startswith("Uber") and cd.profile.sic == "7389"
    assert cd.historicals.v("revenue", "FY2025") == pytest.approx(52017)
    codes = {f.code for f in cd.flags}
    assert "ni_far_above_oi" in codes and "mcap_unchecked" in codes
    assert not cd.hard_stops
    assert steps and cd.steps == steps
    assert cd.analysis.m("operating_margin", "FY2025") == pytest.approx(5565 / 52017)


def test_grab_offline_flags(svc):
    cd = build_company_data("GRAB", svc, today=date(2026, 10, 14))
    codes = {f.code for f in cd.flags}
    assert {"ltm_unavailable", "stale_filing", "negative_fcf"} <= codes
    stale = next(f for f in cd.flags if f.code == "stale_filing")
    assert stale.numbers == {"age_days": 222} and "20-F filed 2026-03-06" in stale.message
    fcf = next(f for f in cd.flags if f.code == "negative_fcf")
    assert fcf.numbers["fcf"] == pytest.approx(79 - 97)
    assert cd.profile.foreign_filer and cd.profile.taxonomy == "ifrs-full"


def test_unknown_ticker(svc):
    with pytest.raises(DataDeskError):
        build_company_data("ZZZZ", svc)


def test_deterministic(svc):
    a = build_company_data("AAPL", svc, today=date(2026, 10, 14))
    b = build_company_data("AAPL", svc, today=date(2026, 10, 14))
    assert a.flags == b.flags
    assert {k: {p: v.value for p, v in d.items()} for k, d in a.historicals.lines.items()} == \
           {k: {p: v.value for p, v in d.items()} for k, d in b.historicals.lines.items()}
