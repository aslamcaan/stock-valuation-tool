"""SEC EDGAR: ticker list, companyfacts (XBRL), submissions, filing documents.

SEC fair-access policy: declare a User-Agent with name and email, max 10 requests/second.
"""
from __future__ import annotations

from dataclasses import dataclass

from core.cache import Cache, Cached
from core.http import DataSourceError, RateLimiter, cache_key, get

SOURCE = "SEC EDGAR"
TICKERS_URL = "https://www.sec.gov/files/company_tickers_exchange.json"
COMPANYFACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
SUBMISSIONS_PAGE_URL = "https://data.sec.gov/submissions/{name}"
ARCHIVE_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/{doc}"

_LIMITER = RateLimiter(per_second=9)  # stay safely under the 10 req/s limit


@dataclass(frozen=True)
class Filing:
    form: str
    accession: str
    filing_date: str
    report_date: str
    primary_document: str
    description: str

    def url(self, cik: int) -> str:
        return ARCHIVE_URL.format(cik=int(cik), acc=self.accession.replace("-", ""), doc=self.primary_document)


class EdgarClient:
    def __init__(self, cache: Cache, user_agent: str):
        self.cache = cache
        self.user_agent = user_agent

    def _headers(self) -> dict:
        if "@" not in self.user_agent:
            raise DataSourceError(SOURCE, "SEC_USER_NAME and SEC_USER_EMAIL must be set in .env")
        return {"User-Agent": self.user_agent, "Accept-Encoding": "gzip, deflate"}

    def _json(self, category: str, url: str, force: bool = False) -> Cached:
        return self.cache.get_or_fetch(
            category, cache_key(url),
            lambda: get(SOURCE, url, headers=self._headers(), limiter=_LIMITER).json(), force=force)

    # --- search universe -------------------------------------------------------------
    def company_tickers(self) -> Cached:
        """Rows of {cik, name, ticker, exchange} for every SEC-registered listed company."""
        def fetch():
            raw = get(SOURCE, TICKERS_URL, headers=self._headers(), limiter=_LIMITER).json()
            cols = raw["fields"]
            return [dict(zip(cols, row)) for row in raw["data"]]
        return self.cache.get_or_fetch("reference", cache_key(TICKERS_URL), fetch)

    def cik_for(self, ticker: str) -> int | None:
        t = ticker.upper().strip()
        for row in self.company_tickers().payload:
            if str(row["ticker"]).upper() == t:
                return int(row["cik"])
        return None

    # --- financial data --------------------------------------------------------------
    def companyfacts(self, cik: int) -> Cached:
        return self._json("companyfacts", COMPANYFACTS_URL.format(cik=int(cik)))

    def submissions(self, cik: int) -> Cached:
        return self._json("filings", SUBMISSIONS_URL.format(cik=int(cik)))

    def filings(self, cik: int, forms: set[str] | None = None, include_older: bool = False) -> list[Filing]:
        """Filing list, newest first. `include_older` also reads the paged older-filings files."""
        sub = self.submissions(cik).payload
        blocks = [sub["filings"]["recent"]]
        if include_older:
            for f in sub["filings"].get("files", []):
                blocks.append(self._json("filings", SUBMISSIONS_PAGE_URL.format(name=f["name"])).payload)
        out: list[Filing] = []
        for b in blocks:
            for i, form in enumerate(b["form"]):
                if forms and form not in forms:
                    continue
                out.append(Filing(form=form, accession=b["accessionNumber"][i], filing_date=b["filingDate"][i],
                                  report_date=b.get("reportDate", [""] * len(b["form"]))[i] or "",
                                  primary_document=b["primaryDocument"][i],
                                  description=b.get("primaryDocDescription", [""] * len(b["form"]))[i] or ""))
        out.sort(key=lambda f: f.filing_date, reverse=True)
        return out

    def document(self, cik: int, filing: Filing) -> Cached:
        """Raw text/HTML of a filing's primary document (cached 30 days)."""
        url = filing.url(cik)
        return self.cache.get_or_fetch(
            "filings", cache_key(url),
            lambda: get(SOURCE, url, headers=self._headers(), limiter=_LIMITER, timeout=60).text)
