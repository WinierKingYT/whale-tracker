import pytest

from whale_tracker import execution
from whale_tracker.execution import net_return_pct


def test_round_trip_at_unchanged_price_loses_the_costs():
    _, pnl = net_return_pct(100.0, "expired", 100.0, 100.0)
    expected_costs = 2 * (execution.HALF_SPREAD_PCT + execution.SLIPPAGE_PCT) + 2 * execution.TAKER_FEE_PCT
    assert pnl == pytest.approx(-expected_costs, rel=0.01)


def test_stop_fills_at_the_worse_of_level_and_observed_price():
    gapped, _ = net_return_pct(100.0, "stopped_out", 95.0, 90.0)
    touched, _ = net_return_pct(100.0, "stopped_out", 95.0, 95.0)
    assert gapped < 90.0 < touched < 95.0


def test_take_profit_is_a_limit_fill_without_price_improvement():
    fill, pnl = net_return_pct(100.0, "take_profit", 110.0, 120.0)
    assert fill == 110.0
    assert pnl < 0.10  # entry costs + fees still paid


def test_unknown_exit_kind_is_rejected():
    with pytest.raises(ValueError):
        net_return_pct(100.0, "teleported", 1.0, 1.0)
