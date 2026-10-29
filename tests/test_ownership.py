"""Phase 12: ownership, insider activity, short interest and forensic scores, offline (recorded SEC filings)."""
from pathlib import Path
from types import SimpleNamespace

import pytest

from data_desk.ownership import build_ownership, parse_13g, parse_form4
from engine.forensic import (BENEISH_COEF, BENEISH_CONST, Z_DOUBLE_PRIME, Z_ORIGINAL, altman, beneish,
                             forensic_scores)
from tests.engine_fixtures import engine_inputs

FIX = Path(__file__).parent / "fixtures" / "ownership"


def xml(name):
    return (FIX / name).read_text(encoding="utf-8")


# --- Form 4 and Schedule 13G parsing ------------------------------------------------------------------------------
def test_form4_parsed_with_codes_and_values():
    trades = parse_form4(xml("cvx_form4.xml"), "2026-10-21", "u")
    assert trades and all(t.owner == "Pate R. Hewitt" and t.role == "Chief Legal Officer" for t in trades)
    ex = [t for t in trades if t.code == "M"]
    assert ex and ex[0].shares == 2400 and ex[0].price == 132.69 and ex[0].action == "option exercise"
    for t in trades:
        if t.price:
            assert t.value == pytest.approx(t.shares * t.price)  # value computed by code
    assert all(t.plan_10b5_1 for t in trades)


def test_form4_open_market_buy():
    trades = parse_form4(xml("grab_form4_buy.xml"), "2026-09-21", "u")
    buys = [t for t in trades if t.code == "P"]
    assert buys and buys[0].action == "open-market purchase" and buys[0].value > 0


def test_13g_takes_the_largest_reporting_person_and_event_date():
    h = parse_13g(xml("cvx_13g.xml"), "SCHEDULE 13G/A", "2026-05-15", "u")
    assert h.name in ("Warren E. Buffett", "Berkshire Hathaway Inc.") and h.percent == 4.2
    assert h.shares == 84375856 and h.event_date == "2026-03-31"


class FakeEdgar:
    def recent_filings_fresh(self, cik, forms):
        return ([{"form": "4/A", "filing_date": "2026-10-22", "items": "", "description": "", "url": "f4"},
                 {"form": "4", "filing_date": "2026-10-21", "items": "", "description": "", "url": "f4"},
                 {"form": "4", "filing_date": "2026-09-22", "items": "", "description": "", "url": "buy"},
                 {"form": "4", "filing_date": "2025-01-01", "items": "", "description": "", "url": "old"},
                 {"form": "SCHEDULE 13G/A", "filing_date": "2026-05-15", "items": "", "description": "", "url": "g"},
                 {"form": "SC 13G", "filing_date": "2024-02-01", "items": "", "description": "", "url": "x"}],
                "t")

    def raw_xml(self, url):
        name = {"f4": "cvx_form4.xml", "buy": "grab_form4_buy.xml", "g": "cvx_13g.xml"}[url]
        return SimpleNamespace(payload=xml(name))


class FakeFinra:
    def short_interest(self, symbol, today):
        return SimpleNamespace(payload=[{"settlementDate": "2026-10-15", "currentShortPositionQuantity": 20_000_000,
                                         "changePercent": 8.46, "daysToCoverQuantity": 3.68,
                                         "averageDailyVolumeQuantity": 6_964_815}])


class BlockedFmp:
    def call(self, *a, **k):
        from core.http import DataSourceError
        raise DataSourceError("FMP", "HTTP 402: premium endpoint")


def test_build_ownership_summary_and_notes():
    from datetime import date
    svc = SimpleNamespace(edgar=FakeEdgar(), finra=FakeFinra(), fmp=BlockedFmp())
    own = build_ownership(svc, 93410, "CVX", 2000.0, date(2026, 10, 29))
    s = own.summary()
    single = parse_form4(xml("cvx_form4.xml"), "2026-10-21", "u")
    assert len(own.trades) == len(single)  # the 4/A restating the same table is counted once
    assert s["buys"] == 0  # the GRAB Form 4 in the feed is about another issuer: excluded
    assert s["sells"] == sum(t.code == "S" for t in single) and s["planned_sells"] == s["sells"]
    assert all(t.filed >= "2026-05-02" for t in own.trades)  # the 2025 Form 4 is outside 180 days
    assert own.short[0]["pct_of_shares"] == pytest.approx(0.01)  # 20m short / 2,000m shares, by code
    assert own.short[0]["change_pct"] == pytest.approx(0.0846)
    assert own.holders[0].percent == 4.2
    notes = " ".join(own.notes)
    assert "not available on the current FMP plan" in notes and "older Schedule 13D/13G" in notes
    assert "concern other issuers" in notes and "counted once" in notes and own.holders[0].filer_cik


def test_one_failing_section_keeps_the_others():
    from datetime import date

    class BrokenFinra:
        def short_interest(self, symbol, today):
            raise ValueError("not JSON")
    own = build_ownership(SimpleNamespace(edgar=FakeEdgar(), finra=BrokenFinra(), fmp=BlockedFmp()), 93410, "CVX",
                          2000.0, date(2026, 10, 29))
    assert own.trades and own.holders and any("Short section unavailable" in n for n in own.notes)


def test_13f_quarter_waits_for_the_filing_deadline():
    from datetime import date
    from data_desk.ownership import last_13f_quarter
    assert last_13f_quarter(date(2026, 10, 29)) == (2026, 2)   # Q3 13Fs are due 14 November
    assert last_13f_quarter(date(2026, 11, 20)) == (2026, 3)
    assert last_13f_quarter(date(2026, 2, 1)) == (2025, 3)     # Q4 not yet due; roll back a year
    assert last_13f_quarter(date(2026, 2, 20)) == (2025, 4)


def test_13d_reporting_person_layout():
    doc = """<edgarSubmission><headerData><filerInfo><filer><filerCredentials><cik>0000000007</cik>
    </filerCredentials></filer></filerInfo></headerData><formData><coverPageHeader><dateOfEvent>06/30/2026
    </dateOfEvent></coverPageHeader><reportingPersons><reportingPersonInfo><reportingPersonName>Activist LP
    </reportingPersonName><aggregateAmountOwned>12500000</aggregateAmountOwned><percentOfClass>6.1</percentOfClass>
    </reportingPersonInfo></reportingPersons></formData></edgarSubmission>"""
    h = parse_13g(doc, "SCHEDULE 13D", "2026-07-02", "u")
    assert (h.name, h.shares, h.percent, h.filer_cik, h.event_date) == ("Activist LP", 12500000, 6.1,
                                                                        "0000000007", "2026-06-30")


# --- forensic scores -----------------------------------------------------------------------------------------------
@pytest.fixture(scope="module")
def ko():
    return engine_inputs("KO")


@pytest.fixture(scope="module")
def grab():
    return engine_inputs("GRAB")


def test_beneish_formula(ko):
    h = ko.historicals
    s = beneish(h, "2080", h.fy_labels[-1], h.fy_labels[-2])
    assert s.value == pytest.approx(BENEISH_CONST + sum(BENEISH_COEF[k] * v for k, v in s.components.items()))
    rev, rev0 = h.v("revenue", h.fy_labels[-1]), h.v("revenue", h.fy_labels[-2])
    assert s.components["SGI"] == pytest.approx(rev / rev0)
    assert s.value < -1.78 and "no sign" in s.reading
    assert {i["line"] for i in s.inputs} >= {"revenue", "receivables", "total_assets", "cfo"}  # traced


def test_altman_original_for_a_manufacturer(ko):
    h, mc = ko.historicals, ko.market_cap.value
    s = altman(h, "2080", h.fy_labels[-1], mc)
    assert s.name == "Altman Z-score" and set(s.components) == set(Z_ORIGINAL)
    assert s.components["X4"] == pytest.approx(mc / h.v("total_liabilities", h.fy_labels[-1]))
    assert s.value == pytest.approx(sum(Z_ORIGINAL[k] * v for k, v in s.components.items()))
    assert "safe" in s.reading


def test_altman_double_prime_flags_an_accumulated_deficit_with_net_cash(grab):
    h = grab.historicals
    s = altman(h, "7372", h.fy_labels[-1], None)
    assert s.name == "Altman Z''-score" and set(s.components) == set(Z_DOUBLE_PRIME)
    assert "distress" in s.reading and any("accumulated deficit" in n and "net cash" in n for n in s.notes)


def test_financials_and_missing_inputs_are_not_scored(ko):
    h = ko.historicals
    assert beneish(h, "6021", h.fy_labels[-1], h.fy_labels[-2]).reading == "not meaningful for banks and insurers"
    assert altman(h, "6311", h.fy_labels[-1], 1.0).value is None
    s = altman(h, "2080", h.fy_labels[-1], None)  # manufacturer without a market cap
    assert s.value is None and "market value of equity" in s.reading


def test_forensic_scores_series(ko):
    out = forensic_scores(ko.historicals, "2080", ko.market_cap.value)
    assert len(out["beneish"]) == len(ko.historicals.fy_labels) - 1 and len(out["altman"]) == 1


def test_double_prime_figures_are_numbers_for_the_ai(grab):
    s = altman(grab.historicals, "7372", grab.historicals.fy_labels[-1], None)
    assert s.figures["distress_below"] == 1.10 and s.figures["retained_earnings_m"] < 0
    assert f"{s.figures['score_without_x2']:.2f}" in s.notes[0]  # the note's number is in the payload as a number


def test_forensic_runs_in_reporting_currency_and_converts_market_cap(ko):
    from desks.pipeline import _forensic
    h = ko.historicals
    last = h.fy_labels[-1]

    class Scaled:  # "US$" statements at 1 local = 0.5 US$
        currency = "USD"
        fy_labels = h.fy_labels

        def v(self, line, p):
            x = h.v(line, p)
            return None if x is None else x * 0.5
    local = SimpleNamespace(**{k: getattr(h, k) for k in ("fy_labels", "get", "v")}, currency="EUR")
    cd = SimpleNamespace(historicals=local, historicals_usd=Scaled(), profile=SimpleNamespace(sic="2080"))
    model = SimpleNamespace(inputs=SimpleNamespace(market_cap=SimpleNamespace(value=100.0)))
    out = _forensic(cd, model)
    z = out["altman"][0]
    mc_in = next(i for i in z.inputs if i["line"] == "market_cap")
    assert mc_in["value"] == pytest.approx(200.0) and "EUR" in mc_in["source"] and last in mc_in["source"]


# --- FINRA client (recorded response) -------------------------------------------------------------------------------
class _Resp:
    def __init__(self, status, text):
        self.status_code, self.text = status, text

    def json(self):
        import json
        return json.loads(self.text)


def test_finra_client_request_and_sorting(tmp_path, monkeypatch):
    from datetime import date
    import datasources.finra as fin
    from core.cache import Cache
    sent = {}

    def post(url, json, headers, timeout):
        sent.update(json)
        return _Resp(200, (FIX / "finra_cvx.json").read_text(encoding="utf-8"))
    monkeypatch.setattr(fin.requests, "post", post)
    rows = fin.FinraClient(Cache(tmp_path)).short_interest("brk-b", date(2026, 10, 29)).payload
    assert sent["compareFilters"][0]["fieldValue"] == "BRKB"
    assert sent["dateRangeFilters"][0] == {"fieldName": "settlementDate", "startDate": "2026-07-01",
                                           "endDate": "2026-10-29"}
    dates = [r["settlementDate"] for r in rows]
    assert dates == sorted(dates) and rows[-1]["currentShortPositionQuantity"] > 0


@pytest.mark.parametrize("status,text", [(200, "<html>maintenance</html>"), (200, '{"error": "bad"}'),
                                         (500, "oops")])
def test_finra_client_bad_responses_raise_a_source_error(tmp_path, monkeypatch, status, text):
    from datetime import date
    import datasources.finra as fin
    from core.cache import Cache
    from core.http import DataSourceError
    monkeypatch.setattr(fin.requests, "post", lambda *a, **k: _Resp(status, text))
    with pytest.raises(DataSourceError):
        fin.FinraClient(Cache(tmp_path)).short_interest("CVX", date(2026, 10, 29))
