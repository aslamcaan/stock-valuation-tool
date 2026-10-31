"""Extract standardised annual + LTM historicals from SEC companyfacts JSON.

Pure functions over the companyfacts dict: no network. Rules:
- Annual values come from annual forms (10-K, 20-F, 40-F and amendments) with a ~1-year duration.
- Restatements: for each period the most recently *filed* value wins.
- Fiscal years are labelled by the year they end in (a year ending in the first week of January
  belongs to the prior year, for 52/53-week calendars).
- LTM (durations) = latest FY + current YTD - prior-year YTD, from 10-Q facts. Balance-sheet LTM
  uses the latest interim balance sheet. If no interim XBRL exists, LTM is not built here.
- Money is normalised to millions; share counts to millions; per-share values unchanged.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta

from data_desk.tags import CONVERTIBLE_TAGS, DEI_SHARES, LINES, OPT, Line
from engine.dates import years_earlier
from engine.model import Historicals, Period
from engine.values import MILLIONS, PER_SHARE, SHARES_M, Value

ANNUAL_FORMS = {"10-K", "10-K/A", "10-KT", "20-F", "20-F/A", "40-F", "40-F/A"}
INTERIM_FORMS = {"10-Q", "10-Q/A", "6-K", "6-K/A"}
SOURCE = "SEC EDGAR companyfacts"
SPINE = ("revenue", "net_income_attributable", "cfo", "operating_income")


def _d(s: str) -> date:
    return date.fromisoformat(s)


def fy_label(end: date) -> str:
    year = end.year - 1 if end.month == 1 and end.day <= 7 else end.year
    return f"FY{year}"


def _days(f: dict) -> int | None:
    return (_d(f["end"]) - _d(f["start"])).days if "start" in f else None


class CompanyFacts:
    def __init__(self, companyfacts: dict, fetched_at: str | None = None):
        self.raw = companyfacts
        self.facts = companyfacts.get("facts", {})
        self.fetched_at = fetched_at
        self.currency = self._reporting_currency()

    # --- basics ----------------------------------------------------------------------------
    def _reporting_currency(self) -> str:
        counts: dict[str, int] = defaultdict(int)
        for tax, tag in (("us-gaap", "Assets"), ("ifrs-full", "Assets"), ("us-gaap", "Revenues"),
                         ("ifrs-full", "Revenue"), ("us-gaap", "RevenueFromContractWithCustomerExcludingAssessedTax")):
            for unit, rows in self.facts.get(tax, {}).get(tag, {}).get("units", {}).items():
                if "/" not in unit:
                    counts[unit] += sum(1 for r in rows if r.get("form") in ANNUAL_FORMS)
        return max(counts, key=counts.get) if counts else "USD"

    @property
    def taxonomy(self) -> str:
        g = len(self.facts.get("us-gaap", {}))
        i = len(self.facts.get("ifrs-full", {}))
        return "ifrs-full" if i > g else "us-gaap"

    def rows(self, tax: str, tag: str, unit_kind: str) -> list[dict]:
        units = self.facts.get(tax, {}).get(tag, {}).get("units", {})
        if unit_kind == "money":
            return units.get(self.currency, [])
        if unit_kind == "shares":
            return units.get("shares", [])
        return units.get(f"{self.currency}/shares", [])

    # --- period discovery --------------------------------------------------------------------
    def fiscal_year_ends(self, max_years: int = 10) -> list[date]:
        ends: set[date] = set()
        for name in SPINE:
            for alt in LINES[name].alternatives:
                for tax, tag in alt:
                    if (tax, tag) == OPT:
                        continue
                    for r in self.rows(tax, tag, "money"):
                        d = _days(r)
                        if r.get("form") in ANNUAL_FORMS and d and 340 <= d <= 380:
                            ends.add(_d(r["end"]))
        # collapse near-duplicate ends (52/53-week calendars tag a few days apart only across years)
        out: list[date] = []
        for e in sorted(ends):
            if out and (e - out[-1]).days < 300:
                out[-1] = max(out[-1], e)
            else:
                out.append(e)
        return out[-max_years:]

    def latest_interim_end(self, last_fy_end: date) -> date | None:
        best = None
        for name in SPINE:
            for alt in LINES[name].alternatives:
                for tax, tag in alt:
                    if (tax, tag) == OPT:
                        continue
                    for r in self.rows(tax, tag, "money"):
                        if r.get("form") in INTERIM_FORMS and "start" in r and _d(r["end"]) > last_fy_end:
                            e = _d(r["end"])
                            best = e if best is None or e > best else best
        return best

    # --- fact lookup ---------------------------------------------------------------------------
    def _pick(self, rows: list[dict], end: date, *, start: date | None = None, annual: bool | None = None,
              duration: bool, tol_days: int = 3) -> dict | None:
        cands = []
        for r in rows:
            if abs((_d(r["end"]) - end).days) > tol_days:
                continue
            if duration != ("start" in r):
                continue
            form = r.get("form", "")
            if annual is True and form not in ANNUAL_FORMS:
                continue
            if annual is False and form not in INTERIM_FORMS | ANNUAL_FORMS:
                continue
            if duration:
                d = _days(r)
                if start is not None:
                    if abs((_d(r["start"]) - start).days) > tol_days:
                        continue
                elif not (340 <= d <= 380):
                    continue
            cands.append(r)
        if not cands:
            return None
        return max(cands, key=lambda r: (r.get("filed", ""), r.get("accn", "")))  # latest filed = restated

    def fact(self, tax: str, tag: str, unit_kind: str, end: date, *, duration: bool,
             start: date | None = None, annual: bool | None = True, tol_days: int = 3) -> dict | None:
        return self._pick(self.rows(tax, tag, unit_kind), end, start=start, annual=annual, duration=duration,
                          tol_days=tol_days)

    def convertible_evidence(self, since: date) -> list[str]:
        out = []
        for tax, tag in CONVERTIBLE_TAGS:
            for unit_rows in self.facts.get(tax, {}).get(tag, {}).get("units", {}).values():
                recent = [r for r in unit_rows if _d(r["end"]) >= since and r.get("val")]
                if recent:
                    r = max(recent, key=lambda x: x["end"])
                    out.append(f"{tax}:{tag} = {r['val']:,} at {r['end']} ({r.get('form')} filed {r.get('filed')})")
                    break
        return out

    def dei_shares(self) -> tuple[float, str, list[dict]] | None:
        tax, tag = DEI_SHARES
        rows = self.facts.get(tax, {}).get(tag, {}).get("units", {}).get("shares", [])
        if not rows:
            return None
        latest_end = max(r["end"] for r in rows)
        at = [r for r in rows if r["end"] == latest_end]
        latest_accn = max(at, key=lambda r: r.get("filed", ""))["accn"]
        same = [r for r in at if r["accn"] == latest_accn]
        return sum(r["val"] for r in same), latest_end, same


def _scale(val: float, line: Line) -> float:
    return val / 1e6 if line.unit in ("money", "shares") else float(val)


def _unit(line: Line) -> str:
    return {"money": MILLIONS, "shares": SHARES_M, "per_share": PER_SHARE}[line.unit]


def _filing(r: dict) -> str:
    return f"{r.get('form')} filed {r.get('filed')} ({r.get('accn')})"


class Extractor:
    def __init__(self, cf: CompanyFacts):
        self.cf = cf

    @staticmethod
    def _tags(alt: tuple) -> tuple[tuple[tuple[str, str], ...], bool]:
        """(tags, optional). Optional sums need their first tag; the others are added when reported."""
        return (alt[1:], True) if alt[0] == OPT else (alt, False)

    def _collect(self, alt: tuple, fetch) -> list[tuple[str, str, dict]] | None:
        """Facts for each tag of an alternative via `fetch(tax, tag)`, or None if a required tag is missing."""
        tags, optional = self._tags(alt)
        rows = []
        for i, (tax, tag) in enumerate(tags):
            r = fetch(tax, tag)
            if r is None:
                if optional and i > 0:
                    continue
                return None
            rows.append((tax, tag, r))
        return rows or None

    def _value(self, line: Line, rows: list, period: str) -> Value:
        parts = [Value(_scale(r["val"], line), self.cf.currency if line.unit != "shares" else None, _unit(line),
                       period, r.get("src", SOURCE), f"{tax}:{tag}", self.cf.fetched_at, _filing(r))
                 for tax, tag, r in rows]
        if len(parts) == 1:
            return parts[0]
        return Value(sum(p.value for p in parts), parts[0].currency, parts[0].unit, period, "calculated",
                     tag=" + ".join(p.tag for p in parts), formula=" + ".join(p.tag.split(":")[1] for p in parts),
                     inputs=tuple(parts), input_names=tuple(p.tag for p in parts))

    def _alt_value(self, line: Line, alt: tuple, period: Period) -> Value | None:
        rows = self._collect(alt, lambda tax, tag: self.cf.fact(tax, tag, line.unit, period.end,
                                                                 duration=line.kind == "duration"))
        return None if rows is None else self._value(line, rows, period.label)

    def annual_line(self, name: str, fy: list[Period]) -> tuple[dict[str, Value], list[dict]]:
        line = LINES[name]
        recent = fy[-5:]
        best, best_cov = None, -1
        for alt in line.alternatives:
            cov = sum(1 for p in recent if self._alt_value(line, alt, p) is not None)
            if cov > best_cov:
                best, best_cov = alt, cov
        out: dict[str, Value] = {}
        log = []
        primary = " + ".join(t for _, t in self._tags(best)[0])
        for p in fy:
            order = [best] + [a for a in line.alternatives if a != best]
            for i, alt in enumerate(order):
                v = self._alt_value(line, alt, p)
                if v is not None:
                    if i > 0:
                        v = v.with_note(f"fallback tag (primary {primary} not reported)")
                    out[p.label] = v
                    log.append({"line": name, "period": p.label, "tag": v.tag, "filing": v.filing,
                                "fallback": i > 0})
                    break
        return out, log

    @staticmethod
    def _same_tags_first(line: Line, ref: Value | None) -> list[tuple]:
        """Alternatives ordered so the one behind the fiscal-year value is tried first (consistent LTM)."""
        alts = list(line.alternatives)
        if ref is None or not ref.tag or not ref.value:  # a zero says nothing about which tag is the real one
            return alts
        ref_tags = set(ref.tag.split(" + "))
        alts.sort(key=lambda a: 0 if {f"{t}:{g}" for t, g in Extractor._tags(a)[0]} >= ref_tags else 1)
        return alts

    def ltm_line(self, name: str, fy_last: Period, ltm: Period, prior_ytd_start: date,
                 annual: dict[str, Value]) -> Value | None:
        line = LINES[name]
        fy_val = annual.get(fy_last.label)
        if line.kind == "instant":
            for alt in self._same_tags_first(line, fy_val):
                rows = self._collect(alt, lambda tax, tag: self.cf.fact(tax, tag, line.unit, ltm.end, duration=False,
                                                                        annual=False))
                if rows:
                    return self._value(line, rows, ltm.label)
            return None
        if fy_val is None:
            return None
        prior_end = years_earlier(ltm.end)
        for alt in self._same_tags_first(line, fy_val):
            cur_rows = self._collect(alt, lambda tax, tag: self.cf.fact(
                tax, tag, line.unit, ltm.end, duration=True, start=ltm.ytd_start, annual=False, tol_days=7))
            prior_rows = self._collect(alt, lambda tax, tag: self.cf.fact(
                tax, tag, line.unit, prior_end, duration=True, start=prior_ytd_start, annual=False, tol_days=7))
            if not cur_rows or not prior_rows:
                continue
            if [(t, g) for t, g, _ in cur_rows] != [(t, g) for t, g, _ in prior_rows]:
                continue  # optional parts reported in one year only: not comparable
            cur_v = self._value(line, cur_rows, f"YTD to {ltm.end}")
            prior_v = self._value(line, prior_rows, f"YTD to {prior_end}")
            if line.unit == "shares":  # share counts are averages, not additive: use the current YTD figure
                return cur_v.with_note("LTM share count = current year-to-date weighted average")
            return Value(fy_val.value + cur_v.value - prior_v.value, fy_val.currency, fy_val.unit, ltm.label,
                         "calculated", tag=cur_v.tag, formula=f"{fy_last.label} + YTD {ltm.end} - YTD {prior_end}",
                         inputs=(fy_val, cur_v, prior_v), input_names=(fy_last.label, "current YTD", "prior YTD"))
        return None


def extract(companyfacts: dict, fetched_at: str | None = None, max_years: int = 10) -> Historicals:
    cf = CompanyFacts(companyfacts, fetched_at)
    ends = cf.fiscal_year_ends(max_years)
    notes: list[str] = []
    if not ends:
        return Historicals(cf.currency, cf.taxonomy, [], {}, notes=["No annual financial data found in XBRL."])

    fy: list[Period] = []
    for e in ends:
        fy.append(Period(fy_label(e), e, None, "FY"))
    ex = Extractor(cf)
    lines: dict[str, dict[str, Value]] = {}
    tag_log: list[dict] = []
    for name in LINES:
        vals, log = ex.annual_line(name, fy)
        lines[name] = vals
        tag_log += log

    periods = list(fy)
    last = fy[-1]
    interim_end = cf.latest_interim_end(last.end)
    if interim_end:
        ytd_start = last.end + timedelta(days=1)
        prior_ytd_start = (fy[-2].end + timedelta(days=1)) if len(fy) > 1 else years_earlier(ytd_start)
        months = round((interim_end - ytd_start).days / 30.4)
        ltm = Period(f"LTM {interim_end.isoformat()}", interim_end, None, "LTM", ytd_start, months)
        built = 0
        for name in LINES:
            v = ex.ltm_line(name, last, ltm, prior_ytd_start, lines[name])
            if v is not None:
                lines[name][ltm.label] = v
                built += 1
                tag_log.append({"line": name, "period": ltm.label, "tag": v.tag, "filing": v.filing,
                                "fallback": False})
        if built:
            periods.append(ltm)
        else:
            notes.append(f"Interim filing to {interim_end} found but LTM could not be built from XBRL.")
    else:
        notes.append(f"No interim (10-Q) XBRL after {last.label}; LTM equals {last.label} unless another source fills it.")

    latest = None
    for name in SPINE:
        v = lines[name].get(last.label)
        if v and v.filing:
            form, _, rest = v.filing.partition(" filed ")
            filed, _, accn = rest.partition(" (")
            latest = {"form": form, "filed": filed, "accn": accn.rstrip(")"), "end": last.end.isoformat()}
            break

    dei = cf.dei_shares()
    dei_v = None
    if dei:
        total, end, rows = dei
        dei_v = Value(total / 1e6, None, SHARES_M, f"cover page {end}", rows[0].get("src", SOURCE),
                      "dei:EntityCommonStockSharesOutstanding",
                      fetched_at, _filing(rows[0]),
                      note=f"sum of {len(rows)} share classes" if len(rows) > 1 else None)
        # a cover page tagged with a dropped or extra digit (BABA's FY2026 20-F: 1.86bn vs 18.6bn weighted) must not
        # set the share count: check it against the latest weighted-average count from the statements
        ref = next((lines[n][p.label] for n in ("shares_basic_weighted", "shares_diluted_weighted")
                    for p in reversed(periods) if lines[n].get(p.label) and lines[n][p.label].value), None)
        last_fy_end = fy[-1].end if fy else None
        if last_fy_end is not None and date.fromisoformat(str(end)[:10]) < last_fy_end - timedelta(days=200):
            notes.append(f"Cover-page share count rejected: {dei_v.value:,.1f}m is dated {end}, before the latest "
                         f"fiscal year ({fy[-1].label}, ended {last_fy_end}); the company no longer tags it.")
            dei_v = None
        elif ref is not None and not 0.5 <= dei_v.value / ref.value <= 2:
            notes.append(f"Cover-page share count rejected: {dei_v.value:,.1f}m ({dei_v.period}) is "
                         f"{dei_v.value / ref.value:.2f}x the weighted-average {ref.value:,.1f}m ({ref.period}); "
                         "likely a tagging error in the filing.")
            dei_v = None

    return Historicals(
        currency=cf.currency, taxonomy=cf.taxonomy, periods=periods, lines=lines, tag_log=tag_log, notes=notes,
        latest_annual_filing=latest, dei_shares=dei_v,
        convertible_evidence=cf.convertible_evidence(since=fy[-2].end if len(fy) > 1 else fy[-1].end),
    )
