"""Golden test 1c (test_grab_judgement): run with the tool's own defaults and produce a bridge table explaining
the gap to the user's value, assumption by assumption, in dollars per share. Run with -s to see the table."""
import pytest

from engine.bridge import dcf_bridge
from engine.valuation import value_company
from tests.engine_fixtures import engine_inputs
from tests.test_golden_grab_engine import M, user_inputs, user_wacc


@pytest.fixture(scope="module")
def bridge():
    tool = value_company(engine_inputs("GRAB"))
    start = user_inputs(user_wacc().wacc.value)
    return tool, dcf_bridge(start, tool.dcf_inputs, tool.per_us_share_factor)


def test_bridge_starts_at_user_value_and_ends_at_tool_value(bridge):
    tool, steps = bridge
    print("\nGrab: user model -> tool defaults (US$ per share)")
    for s in steps:
        ch = "" if s.change is None else f"{s.change:+.2f}"
        val = "error" if s.value_per_share is None else f"{s.value_per_share:.2f}"
        print(f"  {s.name:<38}{ch:>8}{val:>8}   {s.description}{(' [' + s.error + ']') if s.error else ''}")
    assert steps[0].value_per_share == pytest.approx(M["computed"]["value_per_share"]["value"], rel=1e-9)
    assert steps[-1].value_per_share == pytest.approx(tool.per_us_share(tool.dcf.value_per_share), rel=1e-9)


def test_bridge_steps_sum_to_the_gap(bridge):
    tool, steps = bridge
    assert all(s.error is None for s in steps), [s.error for s in steps if s.error]
    total = sum(s.change for s in steps[1:])
    assert total == pytest.approx(steps[-1].value_per_share - steps[0].value_per_share, abs=1e-9)
    assert len(steps) == 10


def test_bridge_names_the_big_driver(bridge):
    """The largest single move should be the margin step (adjusted EBITDA vs GAAP operating margin)."""
    _, steps = bridge
    biggest = max(steps[1:], key=lambda s: abs(s.change))
    assert biggest.name == "Operating margin"
