"""Position sizing (pure). A UK investor holds a US share through Trading 212: pounds are converted to dollars at a
dated GBP/USD rate, with a 0.15% FX fee each way. The rate is the one given (FRED's latest daily observation by
default, dated); it is held for the exit, so the result shows the share-price loss and fee drag, not currency moves."""
from __future__ import annotations

from dataclasses import dataclass

FX_FEE = 0.0015  # Trading 212: 0.15% on each currency conversion


@dataclass(frozen=True)
class Position:
    position_gbp: float        # pounds put in
    entry_price: float         # US$ per share paid
    usd_per_gbp: float         # the dated rate used both ways
    portfolio_gbp: float | None = None
    fee: float = FX_FEE

    @property
    def units(self) -> float:
        return self.position_gbp * (1 - self.fee) * self.usd_per_gbp / self.entry_price

    def value_gbp(self, price: float) -> float:
        """What the shares are worth in pounds after the sell-side FX fee, at the same rate."""
        return self.units * price / self.usd_per_gbp * (1 - self.fee)

    def outcome(self, price: float) -> dict:
        v = self.value_gbp(price)
        pnl = v - self.position_gbp
        return {"price": price, "value_gbp": v, "pnl_gbp": pnl, "pnl_pct": pnl / self.position_gbp,
                "pnl_pct_of_portfolio": None if not self.portfolio_gbp else pnl / self.portfolio_gbp,
                "move_vs_entry": price / self.entry_price - 1}


def size_position(position_gbp: float, entry_price: float, usd_per_gbp: float, portfolio_gbp: float | None,
                  targets: dict[str, float | None], current_price: float | None = None, fee: float = FX_FEE) -> dict:
    """`targets`: name -> US$ share price (bear DCF, base DCF ...). Raises ValueError on a nonsensical input."""
    if position_gbp <= 0 or entry_price <= 0 or usd_per_gbp <= 0:
        raise ValueError("position, entry price and exchange rate must all be above zero")
    if portfolio_gbp is not None and portfolio_gbp < position_gbp:
        raise ValueError("the portfolio cannot be smaller than the position")
    pos = Position(position_gbp, entry_price, usd_per_gbp, portfolio_gbp, fee)
    out = {"position": pos, "units": pos.units, "share_of_portfolio":
           None if not portfolio_gbp else position_gbp / portfolio_gbp,
           "fee_in_gbp": position_gbp * fee, "round_trip_fee_drag": 1 - (1 - fee) ** 2,
           "outcomes": {k: pos.outcome(p) for k, p in targets.items() if p is not None},
           "missing": [k for k, p in targets.items() if p is None]}
    if current_price:
        out["now"] = pos.outcome(current_price)
    return out
