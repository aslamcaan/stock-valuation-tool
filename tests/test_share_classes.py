import pytest

from data_desk import checks
from data_desk.share_classes import class_counts, latest_periodic_accession, one_class_gap

XML = """<xbrli:context id="a"><xbrli:entity><xbrli:segment><xbrldi:explicitMember dimension="us-gaap:StatementClassOfStockAxis">us-gaap:CommonClassAMember</xbrldi:explicitMember></xbrli:segment></xbrli:entity><xbrli:period><xbrli:instant>2026-10-26</xbrli:instant></xbrli:period></xbrli:context>
<xbrli:context id="b"><xbrli:entity><xbrli:segment><xbrldi:explicitMember dimension="us-gaap:StatementClassOfStockAxis">us-gaap:CommonClassBMember</xbrldi:explicitMember></xbrli:segment></xbrli:entity><xbrli:period><xbrli:instant>2026-10-26</xbrli:instant></xbrli:period></xbrli:context>
<xbrli:context id="old"><xbrli:entity><xbrli:segment><xbrldi:explicitMember dimension="x">us-gaap:CommonClassAMember</xbrldi:explicitMember></xbrli:segment></xbrli:entity><xbrli:period><xbrli:instant>2026-07-20</xbrli:instant></xbrli:period></xbrli:context>
<dei:EntityCommonStockSharesOutstanding contextRef="a" decimals="INF" unitRef="shares">2306705341</dei:EntityCommonStockSharesOutstanding>
<dei:EntityCommonStockSharesOutstanding contextRef="b" decimals="INF" unitRef="shares">101787133</dei:EntityCommonStockSharesOutstanding>
<dei:EntityCommonStockSharesOutstanding contextRef="old" decimals="INF" unitRef="shares">2290000000</dei:EntityCommonStockSharesOutstanding>"""


def test_class_counts_read_the_latest_cover_page_by_class():
    date, counts = class_counts(XML)
    assert date == "2026-10-26"
    assert counts == {"ClassA": pytest.approx(2306.705341), "ClassB": pytest.approx(101.787133)}
    assert class_counts(XML.split("<dei:")[0]) is None  # no cover facts


def test_latest_periodic_accession_skips_other_forms():
    sub = {"filings": {"recent": {"form": ["8-K", "10-Q", "10-K"], "accessionNumber": ["x", "y", "z"]}}}
    assert latest_periodic_accession(sub) == "y"
    assert latest_periodic_accession({}) is None


def test_one_class_gap_needs_our_count_confirmed_and_a_matching_subset():
    counts = {"ClassA": 2306.7, "ClassB": 101.8, "ClassF": 1.0}
    assert one_class_gap(counts, 2409.2, 2300.7) == ["ClassA"]  # provider counted Class A only
    assert one_class_gap(counts, 2200.0, 2300.7) is None  # the cover page does not confirm our count
    assert one_class_gap(counts, 2409.2, 1500.0) is None  # the provider matches no subset
    assert one_class_gap({"ClassA": 100.0}, 100.0, 90.0) is None


def test_market_cap_gap_from_a_missing_class_is_amber_not_a_hard_stop():
    gap = {"date": "2026-10-26", "counts": {"ClassA": 2306.7, "ClassB": 101.8}, "covered": ["ClassA"]}
    f = checks.market_cap(429648.3, 410308.6, "FMP", "Shares 2,409.2m.", True, gap)
    assert [x.code for x in f] == ["mcap_provider_share_classes"] and not f[0].is_hard_stop
    assert "ClassA" in f[0].message and "ClassB" in f[0].message
    f = checks.market_cap(429648.3, 410308.6, "FMP", "Shares 2,409.2m.", True)
    assert [x.code for x in f] == ["mcap_mismatch"] and f[0].is_hard_stop  # no evidence: still a hard stop
