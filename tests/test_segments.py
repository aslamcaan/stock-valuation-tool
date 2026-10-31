"""Segment figures read from a filing's XBRL instance, matched to the research desk's segments, and the SOTP's
corporate-cost line."""
import pytest

from data_desk.segments import latest_year, match_names, member_label, segment_facts
from engine.sotp import Segment, run_sotp

XML = """<?xml version="1.0"?>
<xbrl xmlns="http://www.xbrl.org/2003/instance" xmlns:xbrldi="http://xbrl.org/2006/xbrldi"
      xmlns:us-gaap="http://fasb.org/us-gaap/2025" xmlns:srt="http://fasb.org/srt/2025" xmlns:ko="http://ko">
 {contexts}
 {facts}
</xbrl>"""


def ctx(cid, members, start, end):
    m = "".join(f'<xbrldi:explicitMember dimension="{d}">{v}</xbrldi:explicitMember>' for d, v in members)
    return (f'<context id="{cid}"><entity><identifier scheme="x">1</identifier><segment>{m}</segment></entity>'
            f'<period><startDate>{start}</startDate><endDate>{end}</endDate></period></context>')


def ko_like() -> str:
    seg, op = "us-gaap:StatementBusinessSegmentsAxis", ("srt:ConsolidationItemsAxis", "us-gaap:OperatingSegmentsMember")
    contexts, facts = [], []
    data = {"ko:NorthAmericaSegmentMember": (19586, 5070, 18000), "ko:EuropeMiddleEastAfricaMember": (11513, 4298, 11000),
            "ko:BottlingInvestmentsMember": (5735, 426, 6000)}
    for k, (member, (rev, oi, prev)) in enumerate(data.items()):
        contexts.append(ctx(f"c{k}", [op, (seg, member)], "2025-01-01", "2025-12-31"))
        contexts.append(ctx(f"p{k}", [op, (seg, member)], "2024-01-01", "2024-12-31"))
        facts += [f'<us-gaap:Revenues contextRef="c{k}" unitRef="usd" decimals="-6">{rev * 1_000_000}</us-gaap:Revenues>',
                  f'<us-gaap:OperatingIncomeLoss contextRef="c{k}" unitRef="usd">{oi * 1_000_000}</us-gaap:OperatingIncomeLoss>',
                  f'<us-gaap:Revenues contextRef="p{k}" unitRef="usd">{prev * 1_000_000}</us-gaap:Revenues>']
    # an aggregate member and an elimination are not segments; a quarter is not a year
    contexts.append(ctx("agg", [(seg, "srt:ReportableSegmentAggregationBeforeOtherOperatingSegmentMember")],
                        "2025-01-01", "2025-12-31"))
    contexts.append(ctx("elim", [("srt:ConsolidationItemsAxis", "us-gaap:IntersegmentEliminationMember"),
                                 (seg, "ko:NorthAmericaSegmentMember")], "2025-01-01", "2025-12-31"))
    contexts.append(ctx("q", [(seg, "ko:NorthAmericaSegmentMember")], "2025-10-01", "2025-12-31"))
    facts += ['<us-gaap:Revenues contextRef="agg" unitRef="usd">99000000000</us-gaap:Revenues>',
              '<us-gaap:Revenues contextRef="elim" unitRef="usd">-500000000</us-gaap:Revenues>',
              '<us-gaap:Revenues contextRef="q" unitRef="usd">5000000000</us-gaap:Revenues>']
    return XML.format(contexts="\n".join(contexts), facts="\n".join(facts))


def test_segment_revenue_and_operating_income_from_xbrl():
    end, rows, prior = latest_year(segment_facts(ko_like()))
    assert end == "2025-12-31" and set(rows) == {"North America", "Europe Middle East Africa", "Bottling Investments"}
    na = rows["North America"]
    assert na["revenue"] == 19586 and na["operating_income"] == 5070  # millions; the elimination and quarter ignored
    assert na["growth"] == pytest.approx(19586 / 18000 - 1)


def test_member_labels():
    assert member_label("msft:IntelligentCloudMember") == "Intelligent Cloud"
    assert member_label("ko:LatinAmericaSegmentMember") == "Latin America"
    assert member_label("ko:A.PacificMember") == "A. Pacific"


def test_research_names_matched_by_operating_income_then_words():
    _, rows, _ = latest_year(segment_facts(ko_like()))
    research = [{"name": "EMEA", "profit_millions": 4298, "comparable_us_tickers": ["KDP"]},
                {"name": "Bottling Investments", "profit_millions": None, "comparable_us_tickers": ["COKE"]},
                {"name": "North America", "profit_millions": 5070, "comparable_us_tickers": ["PEP"]}]
    m = match_names(rows, research)
    assert m["Europe Middle East Africa"]["name"] == "EMEA"  # identical operating income
    assert m["Bottling Investments"]["comparable_us_tickers"] == ["COKE"]  # shared words


def test_corporate_costs_reduce_the_sum_of_the_parts():
    a = Segment("A", 1000, 300, metric="EV/EBIT", metric_value=300, multiple=15.0)
    b = Segment("B", 1000, 50, metric="EV/EBIT", metric_value=50, multiple=10.0)
    avg = (300 * 15 + 50 * 10) / 350
    corp = Segment("Corporate and unallocated costs", 0.0, -70, metric="EV/EBIT", metric_value=-70, multiple=avg)
    r = run_sotp([a, b, corp], bridge=-500, shares=100)
    assert r.applicable  # margins 30% vs 5%
    assert r.enterprise_value == pytest.approx(4500 + 500 - 70 * avg)
    assert r.value_per_share == pytest.approx((r.enterprise_value - 500) / 100)
