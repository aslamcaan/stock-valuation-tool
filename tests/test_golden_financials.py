"""PROMPT.md section 10, tests 7-9: JPM (bank), TRV (insurer) and O (REIT) reported KPIs are read correctly from
their 10-Ks (recorded text), and the toolkit routing sends them to the right toolkit."""
import gzip
import json
from pathlib import Path

import pytest

from data_desk.fin_text import reported_kpis
from engine.classify import BANK, INSURER, REIT, toolkit_for_sic

FIX = Path(__file__).parent / "fixtures" / "fin"
EXPECTED = json.loads((FIX / "expected.json").read_text(encoding="utf-8"))


def _text(ticker: str) -> str:
    with gzip.open(FIX / f"{ticker.lower()}_10k.txt.gz", "rt", encoding="utf-8") as f:
        return f.read()


@pytest.mark.parametrize("ticker", ["JPM", "TRV", "O"])
def test_reported_kpis_match_the_10k(ticker):
    case = EXPECTED[ticker]
    got = reported_kpis(_text(ticker), case["toolkit"], case["filing"])
    for key, exp in case["expected"].items():
        assert key in got, f"{ticker} {key} not found"
        assert got[key].value == pytest.approx(exp["value"], abs=1e-6), f"{ticker} {key}: {got[key].quote}"
        assert got[key].quote.lower() in _text(ticker).lower()  # verbatim quote


def test_toolkit_routing():
    assert toolkit_for_sic("6021")[0] == BANK      # JPM: national commercial banks
    assert toolkit_for_sic("6331")[0] == INSURER   # TRV: fire, marine and casualty insurance
    assert toolkit_for_sic("6798")[0] == REIT      # O: real estate investment trusts


def test_requirements_and_toc_entries_are_not_read_as_values():
    from data_desk.fin_text import SPECS, find
    t = ("the Company is subject to a minimum common equity tier 1 capital ratio of 4.5 percent. "
         "Reconciliation of Tangible Book Value Per Common Share (non-GAAP) 76 40 ... "
         "Book value per common share $ 140.44 Tangible book value per common share (non-GAAP) (a) $ 112.51")
    assert find(t, SPECS["bank"]["cet1_ratio"]) is None
    assert find(t, SPECS["bank"]["tbvps"], lambda v: v <= 140.44)[0] == 112.51


def test_numbers_are_read_whole_and_amounts_and_years_are_rejected():
    from data_desk.fin_text import SPECS, find
    assert find("Book value per share 1234.56", SPECS["insurer"]["bvps"]) in (None, (1234.56, "Book value per share 1234.56"))
    assert find("Tangible book value per share (a) 2024 95.11", SPECS["bank"]["tbvps"])[0] == 95.11
    assert find("CET1 capital ratio 25.1 billion", SPECS["bank"]["cet1_ratio"]) is None
    assert find("CET1 capital ratio 1,234 was", SPECS["bank"]["cet1_ratio"]) is None


def test_managed_care_uses_the_corporate_toolkit():
    from engine.classify import CORPORATE
    assert toolkit_for_sic("6324")[0] == CORPORATE   # UNH: health plans, not a book-value insurer
    assert toolkit_for_sic("6311")[0] == INSURER     # life insurance
