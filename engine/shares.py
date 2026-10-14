"""Diluted share count by the treasury stock method (pure)."""
from __future__ import annotations

from engine.values import SHARES_M, Value, calc


def diluted_shares(basic: Value, price: Value | None, rsus: Value | None = None, options: Value | None = None,
                   strike: Value | None = None, eps_dilution: Value | None = None) -> Value:
    """basic + unvested RSUs + in-the-money options x (1 - strike / price).

    When award data is not tagged, the company's own EPS dilution (diluted minus basic weighted shares,
    already computed with the treasury method) is added instead, and the value says so.
    """
    has_awards = (rsus is not None and rsus.value is not None) or (options is not None and options.value)
    if not has_awards and eps_dilution is not None and eps_dilution.value is not None:
        return calc(lambda b, d: b + max(d, 0.0), "basic shares + EPS dilution (diluted - basic weighted shares)",
                    basic.period, SHARES_M, None, basic_shares=basic, eps_dilution=eps_dilution).with_note(
            "option / RSU detail not tagged: the company's own treasury-method dilution from its EPS calculation is used")
    zero = lambda what: Value(0.0, None, SHARES_M, basic.period, "assumed zero", note=f"{what} not reported")  # noqa: E731
    notes = []
    r = rsus if rsus is not None and rsus.value is not None else zero("unvested RSUs")
    if r.source == "assumed zero":
        notes.append("RSUs not reported")
    if (options is not None and options.value and strike is not None and strike.value is not None and price
            and price.value and strike.currency in (None, price.currency)):
        opt = calc(lambda n, k, p: n * max(0.0, 1 - k / p), "options x max(0, 1 - strike / price)", basic.period,
                   SHARES_M, None, options=options, strike=strike, price=price)
    else:
        opt = zero("options (or strike / price)")
        notes.append("option dilution not included (data unavailable)")
    out = calc(lambda b, x, y: b + x + y, "basic shares + unvested RSUs + treasury-method options", basic.period,
               SHARES_M, None, basic_shares=basic, rsus=r, options_dilution=opt)
    return out.with_note("; ".join(notes)) if notes else out
