"""Facts read from a filing's own XBRL instance when SEC companyfacts lags (TSM's 2025 20-F, IFRS 2025 taxonomy)."""
from data_desk.instance import SOURCE, instance_facts, merge

XML = """<?xml version="1.0" encoding="utf-8"?>
<xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance" xmlns:ifrs-full="https://xbrl.ifrs.org/taxonomy/2025-03-27/ifrs-full"
 xmlns:dei="http://xbrl.sec.gov/dei/2025" xmlns:tsm="http://www.tsmc.com/20251231" xmlns:xbrldi="http://xbrl.org/2006/xbrldi"
 xmlns:iso4217="http://www.xbrl.org/2003/iso4217">
  <xbrli:context id="c-1"><xbrli:entity><xbrli:identifier scheme="http://www.sec.gov/CIK">1</xbrli:identifier></xbrli:entity>
    <xbrli:period><xbrli:startDate>2025-01-01</xbrli:startDate><xbrli:endDate>2025-12-31</xbrli:endDate></xbrli:period></xbrli:context>
  <xbrli:context id="c-2"><xbrli:entity><xbrli:identifier scheme="http://www.sec.gov/CIK">1</xbrli:identifier></xbrli:entity>
    <xbrli:period><xbrli:instant>2025-12-31</xbrli:instant></xbrli:period></xbrli:context>
  <xbrli:context id="c-3"><xbrli:entity><xbrli:identifier scheme="http://www.sec.gov/CIK">1</xbrli:identifier>
    <xbrli:segment><xbrldi:explicitMember dimension="ifrs-full:SegmentsAxis">tsm:AsiaMember</xbrldi:explicitMember></xbrli:segment>
    </xbrli:entity><xbrli:period><xbrli:startDate>2025-01-01</xbrli:startDate><xbrli:endDate>2025-12-31</xbrli:endDate></xbrli:period></xbrli:context>
  <xbrli:unit id="twd"><xbrli:measure>iso4217:TWD</xbrli:measure></xbrli:unit>
  <xbrli:unit id="shares"><xbrli:measure>xbrli:shares</xbrli:measure></xbrli:unit>
  <xbrli:unit id="twdps"><xbrli:divide><xbrli:unitNumerator><xbrli:measure>iso4217:TWD</xbrli:measure></xbrli:unitNumerator>
    <xbrli:unitDenominator><xbrli:measure>xbrli:shares</xbrli:measure></xbrli:unitDenominator></xbrli:divide></xbrli:unit>
  <ifrs-full:RevenueFromContractsWithCustomers contextRef="c-1" decimals="-5" unitRef="twd">3809054300000</ifrs-full:RevenueFromContractsWithCustomers>
  <ifrs-full:RevenueFromContractsWithCustomers contextRef="c-1" decimals="-5" unitRef="twd">3809054300000</ifrs-full:RevenueFromContractsWithCustomers>
  <ifrs-full:RevenueFromContractsWithCustomers contextRef="c-3" decimals="-5" unitRef="twd">100</ifrs-full:RevenueFromContractsWithCustomers>
  <ifrs-full:BasicEarningsLossPerShare contextRef="c-1" decimals="2" unitRef="twdps">65.47</ifrs-full:BasicEarningsLossPerShare>
  <ifrs-full:Assets contextRef="c-2" decimals="-5" unitRef="twd">7932842500000</ifrs-full:Assets>
  <dei:EntityCommonStockSharesOutstanding contextRef="c-2" decimals="0" unitRef="shares">25932000000</dei:EntityCommonStockSharesOutstanding>
  <tsm:CustomThing contextRef="c-1" decimals="0" unitRef="twd">5</tsm:CustomThing>
</xbrli:xbrl>"""


def test_instance_facts_in_companyfacts_shape():
    f = instance_facts(XML, "0001-26-1", "20-F", "2026-04-16", 2025)["facts"]
    rev = f["ifrs-full"]["RevenueFromContractsWithCustomers"]["units"]["TWD"]
    assert rev == [{"start": "2025-01-01", "end": "2025-12-31", "val": 3809054300000, "accn": "0001-26-1", "fy": 2025,
                    "fp": "FY", "form": "20-F", "filed": "2026-04-16", "src": SOURCE}]  # repeat and segment dropped
    assert f["ifrs-full"]["BasicEarningsLossPerShare"]["units"]["TWD/shares"][0]["val"] == 65.47
    assets = f["ifrs-full"]["Assets"]["units"]["TWD"][0]
    assert assets["end"] == "2025-12-31" and "start" not in assets and assets["val"] == 7932842500000
    assert "tsm" not in f  # company extensions are not standard lines


def test_merge_never_adds_a_fact_twice():
    extra = instance_facts(XML, "0001-26-1", "20-F", "2026-04-16", 2025)
    have = {"facts": {"dei": {"EntityCommonStockSharesOutstanding": {"units": {"shares": [
        {"end": "2025-12-31", "val": 25932000000, "accn": "0001-26-1", "form": "20-F", "filed": "2026-04-16"}]}}}}}
    out = merge(have, extra)
    assert len(out["facts"]["dei"]["EntityCommonStockSharesOutstanding"]["units"]["shares"]) == 1  # TSM: was summed 2x
    assert "ifrs-full" in out["facts"] and "ifrs-full" not in have["facts"]  # input left unchanged
