"""Successor issuers: predecessor found from the 8-K12B cover page; histories merged only when they agree."""
from types import SimpleNamespace

from data_desk.lineage import annual_fact_count, find_predecessor, merge_facts

SUB = {"name": "NewCo Holdings", "filings": {"recent": {
    "form": ["10-Q", "8-K12B"], "accessionNumber": ["x", "0001193125-26-291990"],
    "primaryDocument": ["q.htm", "d8k12b.htm"], "filingDate": ["2026-08-03", "2026-07-01"],
    "fileNumber": ["001-43384", "001-43384"]}}}
COVER = ("<html><p>Commission File Number 001-02256</p><p>Commission File Number 001-43384</p>"
         "<p>successor registrant pursuant to Rule 12g-3(a)</p></html>")


class Edgar:
    def __init__(self, atoms):
        self.atoms, self.urls = atoms, []

    def raw_xml(self, url):
        self.urls.append(url)
        if url.endswith("d8k12b.htm"):
            return SimpleNamespace(payload=COVER)
        fn = url.split("filenum=")[1].split("&")[0]
        return SimpleNamespace(payload=self.atoms.get(fn, "<feed></feed>"))


def test_predecessor_from_the_cover_page_file_number():
    edgar = Edgar({"001-02256": "<feed><company-info><cik>0000034088</cik></company-info></feed>"})
    cik, how = find_predecessor(SimpleNamespace(edgar=edgar), 2115436, SUB)
    assert cik == 34088 and "cover-page file number" in how
    assert not any("001-43384" in u for u in edgar.urls)  # the successor's own file number is not looked up


def test_no_successor_filing_means_no_predecessor():
    sub = {"filings": {"recent": {"form": ["10-K"], "accessionNumber": ["a"], "primaryDocument": ["d"],
                                  "filingDate": ["2026-02-01"], "fileNumber": ["001-1"]}}}
    assert find_predecessor(SimpleNamespace(edgar=Edgar({})), 5, sub)[0] is None


def test_unresolved_cover_falls_back_to_the_sourced_table_only_for_known_ciks():
    assert find_predecessor(SimpleNamespace(edgar=Edgar({})), 2115436, SUB)[0] == 34088
    assert find_predecessor(SimpleNamespace(edgar=Edgar({})), 999, SUB)[0] is None


def _facts(rows):
    return {"entityName": "x", "facts": {"us-gaap": {"Assets": {"label": "Assets", "units": {"USD": rows}}}}}


def test_merge_keeps_both_histories_and_marks_the_predecessor():
    pred = _facts([{"end": "2025-12-31", "val": 448980e6, "form": "10-K", "fp": "FY", "accn": "p1"}])
    succ = _facts([{"end": "2025-12-31", "val": 448980e6, "form": "10-Q", "fp": "Q2", "accn": "s1"},
                   {"end": "2026-06-30", "val": 464482e6, "form": "10-Q", "fp": "Q2", "accn": "s1"}])
    merged, note = merge_facts(succ, pred, 34088)
    rows = merged["facts"]["us-gaap"]["Assets"]["units"]["USD"]
    assert len(rows) == 3 and rows[0]["cik"] == 34088 and "1 shared figures checked; 0 differ" in note
    assert annual_fact_count(merged) == 1


def test_merge_refuses_histories_that_disagree():
    pred = _facts([{"end": "2025-12-31", "val": 100.0, "form": "10-K", "fp": "FY", "accn": "p1"}])
    succ = _facts([{"end": "2025-12-31", "val": 120.0, "form": "10-Q", "fp": "Q2", "accn": "s1"}])
    merged, note = merge_facts(succ, pred, 1)
    assert merged is None and "not merged" in note
