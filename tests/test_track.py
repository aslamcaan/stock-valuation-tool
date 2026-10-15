"""Track record maths."""
from datetime import date

from engine.track import evaluate, hit_rates

PRICES = {("AAA", date(2026, 1, 1)): 100, ("AAA", date(2026, 1, 31)): 110, ("AAA", date(2026, 10, 1)): 130,
          ("SPY", date(2026, 1, 1)): 500, ("SPY", date(2026, 1, 31)): 505, ("SPY", date(2026, 10, 1)): 550,
          ("XLK", date(2026, 1, 1)): 200, ("XLK", date(2026, 10, 1)): 220}


def price_at(t, d):
    keys = [k for k in PRICES if k[0] == t and k[1] <= d]
    return PRICES[max(keys, key=lambda k: k[1])] if keys else None


def test_evaluate_and_hit_rates():
    call = {"ticker": "AAA", "call_date": "2026-01-01", "price": 100, "fair_value": 140, "rating": "Buy",
            "sector_etf": "XLK"}
    r = evaluate(call, price_at, date(2026, 10, 1))
    assert abs(r.ret - 0.30) < 1e-12 and abs(r.spy_ret - 0.10) < 1e-12 and abs(r.sector_ret - 0.10) < 1e-12
    assert r.toward_fair_value is True
    assert abs(r.horizon_excess["1m"] - (0.10 - 0.01)) < 1e-12 and r.horizon_excess["12m"] is None
    hr = hit_rates([r])
    assert hr["Buy / Strong Buy"]["1m"] == {"calls": 1, "hit_rate": 1.0, "average_excess": r.horizon_excess["1m"]}
    assert hr["Sell / Strong Sell"]["1m"]["calls"] == 0
