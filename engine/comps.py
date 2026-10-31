"""Comparable companies (pure): peer selection rules, multiples, implied prices, industry benchmarking.

Peer set (PROMPT.md 5): candidates in the same SIC code and 0.25x-4x the company's market cap, at least 5.
If fewer qualify, the filter widens step by step (SIC 3-digit, SIC 2-digit, any SIC, 0.1x-10x, nearest by size)
and every widening step is reported.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from statistics import median

MIN_PEERS = 5
SIZE_FLOOR, SIZE_CAP = 0.02, 50.0  # the nearest-by-size fallback never goes beyond these market-cap ratios
MULTIPLES = {
    "pe_forward": ("Forward P/E", "equity"),
    "pe_trailing": ("Trailing P/E", "equity"),
    "ev_sales": ("EV/Sales", "ev"),
    "ev_ebitda": ("EV/EBITDA", "ev"),
    "ev_fcf": ("EV/FCF", "ev"),
}
# Above these a peer's multiple is "not meaningful" (NM, the sell-side convention): earnings or cash flow near zero,
# so the ratio says nothing about value and would swamp the quartiles (e.g. a 5,700x P/E).
NM_ABOVE = {"pe_forward": 100.0, "pe_trailing": 100.0, "ev_sales": 50.0, "ev_ebitda": 100.0, "ev_fcf": 100.0}
BENCHMARKS = {  # metric -> (label, higher is better)
    "revenue_growth": ("Revenue growth", True),
    "operating_margin": ("Operating margin", True),
    "roic": ("ROIC", True),
    "fcf_margin": ("FCF margin", True),
    "net_debt_to_ebitda": ("Net debt / EBITDA", False),
}


def earnings_distorted(net_income: float | None, operating_income: float | None, revenue: float | None) -> bool:
    """Net income far above operating income (one-off tax or investment gains): P/E is not meaningful.
    Same rule as the data-desk flag: gap > 50% of |operating income| and > 5% of revenue."""
    if net_income is None or operating_income is None or not revenue or revenue <= 0:
        return False
    gap = net_income - operating_income
    return gap > 0.5 * abs(operating_income) and gap > 0.05 * revenue


@dataclass
class CompanyMetrics:
    """One company's inputs for comps (US$ millions unless stated)."""
    ticker: str
    name: str
    sic: str
    market_cap: float | None
    price: float | None              # per US share
    revenue: float | None
    ebitda: float | None
    fcf: float | None
    net_income: float | None
    forward_eps: float | None        # consensus next fiscal year, per US share
    debt: float | None
    cash: float | None
    minority: float = 0.0
    period: str = ""
    operating_income: float | None = None
    preferred: float = 0.0
    earnings_flagged: bool = False  # net income distorted in the latest fiscal year (even if not in the LTM)
    benchmarks: dict[str, float | None] = field(default_factory=dict)
    source: str = ""
    # financial-sector toolkits (US$ millions, latest fiscal year)
    common_equity: float | None = None
    tangible_equity: float | None = None
    net_income_common: float | None = None
    ffo: float | None = None
    noi: float | None = None

    @property
    def ev(self) -> float | None:
        if self.market_cap is None or self.debt is None or self.cash is None:
            return None
        return self.market_cap + self.debt - self.cash + (self.minority or 0.0) + (self.preferred or 0.0)

    @property
    def pe_meaningful(self) -> bool:
        return not (self.earnings_flagged or earnings_distorted(self.net_income, self.operating_income, self.revenue))

    def multiples(self) -> dict[str, float | None]:
        ev = self.ev

        def pos(n, d):
            return n / d if n is not None and d and d > 0 and n > 0 else None

        return {"pe_forward": pos(self.price, self.forward_eps),
                "pe_trailing": pos(self.market_cap, self.net_income) if self.pe_meaningful else None,
                "ev_sales": pos(ev, self.revenue), "ev_ebitda": pos(ev, self.ebitda), "ev_fcf": pos(ev, self.fcf)}


def _sic_match(a: str, b: str, digits: int) -> bool:
    return bool(a) and bool(b) and a[:digits] == b[:digits]


def select_peers(company: CompanyMetrics, candidates: list[CompanyMetrics]) -> tuple[list[CompanyMetrics], list[str]]:
    """Apply the brief's filter, widening until at least MIN_PEERS qualify. Returns (peers, steps taken)."""
    mc = company.market_cap or 0.0
    pool = [c for c in candidates if c.ticker != company.ticker and c.market_cap]
    steps = [("same SIC, 0.25x-4x market cap", lambda c: _sic_match(c.sic, company.sic, 4) and 0.25 <= c.market_cap / mc <= 4),
             ("same 3-digit SIC, 0.25x-4x market cap", lambda c: _sic_match(c.sic, company.sic, 3) and 0.25 <= c.market_cap / mc <= 4),
             ("same 2-digit SIC, 0.25x-4x market cap", lambda c: _sic_match(c.sic, company.sic, 2) and 0.25 <= c.market_cap / mc <= 4),
             ("any SIC among the candidates, 0.25x-4x market cap", lambda c: 0.25 <= c.market_cap / mc <= 4),
             ("any SIC, 0.1x-10x market cap", lambda c: 0.1 <= c.market_cap / mc <= 10)]
    taken = []
    if mc <= 0:
        return sorted(pool, key=lambda c: -(c.market_cap or 0))[:8], ["company market cap unknown: all candidates used"]
    for desc, rule in steps:
        peers = [c for c in pool if rule(c)]
        taken.append(f"{desc}: {len(peers)} peers")
        if len(peers) >= MIN_PEERS:
            return peers, taken
    import math
    sized = [c for c in pool if SIZE_FLOOR <= c.market_cap / mc <= SIZE_CAP]
    peers = sorted(sized, key=lambda c: abs(math.log(c.market_cap / mc)))[:max(MIN_PEERS, 8)]
    taken.append(f"nearest {len(peers)} candidates by market cap within {SIZE_FLOOR:g}x-{SIZE_CAP:g}x "
                 f"(fewer than {MIN_PEERS} accepted rather than micro-caps)")
    return peers, taken


def _quartiles(xs: list[float]) -> tuple[float, float, float]:
    s = sorted(xs)
    if len(s) == 1:
        return s[0], s[0], s[0]

    def q(p):
        k = (len(s) - 1) * p
        lo, hi = int(k), min(int(k) + 1, len(s) - 1)
        return s[lo] + (s[hi] - s[lo]) * (k - lo)
    return q(0.25), q(0.5), q(0.75)


@dataclass
class MultipleResult:
    key: str
    label: str
    peer_values: dict[str, float]
    q1: float | None
    median: float | None
    q3: float | None
    company_value: float | None
    implied_price_low: float | None
    implied_price: float | None
    implied_price_high: float | None
    basis: str


@dataclass
class CompsResult:
    peers: list[CompanyMetrics]
    selection_steps: list[str]
    multiples: dict[str, MultipleResult]
    implied_price: float | None          # median of the multiples' implied prices
    benchmarks: dict[str, dict]
    excluded: list[str] = field(default_factory=list)


def implied_from_multiple(key: str, multiple: float, company: CompanyMetrics, shares: float, bridge: float,
                          adr_ratio: float) -> float | None:
    """Per-US-share price implied by applying `multiple` to the company's metric.
    EV multiples: (multiple x metric + bridge) / shares x ADR ratio. P/E: multiple x EPS."""
    if key == "pe_forward":
        return multiple * company.forward_eps if company.forward_eps and company.forward_eps > 0 else None
    metric = {"pe_trailing": company.net_income, "ev_sales": company.revenue, "ev_ebitda": company.ebitda,
              "ev_fcf": company.fcf}[key]
    if metric is None or metric <= 0 or not shares:
        return None
    if key == "pe_trailing" and not company.pe_meaningful:
        return None  # net income inflated by one-off gains
    if key == "pe_trailing":
        return multiple * metric / shares * adr_ratio
    return (multiple * metric + bridge) / shares * adr_ratio


def run_comps(company: CompanyMetrics, peers: list[CompanyMetrics], steps: list[str], shares: float, bridge: float,
              adr_ratio: float = 1.0) -> CompsResult:
    """`bridge` is the signed amount from EV to equity (cash - debt - minorities), `shares` diluted ordinary shares."""
    own = company.multiples()
    res: dict[str, MultipleResult] = {}
    excluded: list[str] = []
    for key, (label, basis) in MULTIPLES.items():
        vals = {p.ticker: m for p in peers if (m := p.multiples()[key]) is not None and m <= NM_ABOVE[key]}
        excluded += [f"{p.ticker} {label} {m:,.0f}x (not meaningful, above {NM_ABOVE[key]:g}x)" for p in peers
                     if (m := p.multiples()[key]) is not None and m > NM_ABOVE[key]]
        if len(vals) < 3:
            res[key] = MultipleResult(key, label, vals, None, None, None, own[key], None, None, None, basis)
            continue
        q1, md, q3 = _quartiles(list(vals.values()))
        res[key] = MultipleResult(key, label, vals, q1, md, q3, own[key],
                                  implied_from_multiple(key, q1, company, shares, bridge, adr_ratio),
                                  implied_from_multiple(key, md, company, shares, bridge, adr_ratio),
                                  implied_from_multiple(key, q3, company, shares, bridge, adr_ratio), basis)
    implied = [m.implied_price for m in res.values() if m.implied_price is not None]
    if res["pe_forward"].implied_price is not None and res["pe_trailing"].implied_price is not None:
        implied.remove(res["pe_trailing"].implied_price)  # forward P/E preferred; avoid double-weighting P/E
    benchmarks = benchmark(company, peers)
    return CompsResult(peers, steps, res, median(implied) if implied else None, benchmarks, excluded)


def benchmark(company: CompanyMetrics, peers: list[CompanyMetrics]) -> dict[str, dict]:
    """Percentile rank of the company against peers (100% = best) and the peer median."""
    out = {}
    for key, (label, higher_better) in BENCHMARKS.items():
        mine = company.benchmarks.get(key)
        vals = [p.benchmarks.get(key) for p in peers if p.benchmarks.get(key) is not None]
        if mine is None or len(vals) < 3:
            out[key] = {"label": label, "company": mine, "peer_median": median(vals) if vals else None,
                        "percentile": None, "peers": len(vals)}
            continue
        better = sum(1 for v in vals if (v < mine if higher_better else v > mine))
        same = sum(1 for v in vals if v == mine)
        out[key] = {"label": label, "company": mine, "peer_median": median(vals),
                    "percentile": (better + 0.5 * same) / len(vals), "peers": len(vals)}
    return out
