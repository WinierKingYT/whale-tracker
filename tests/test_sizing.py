import pytest

from whale_tracker import approval, paper_trading
from whale_tracker.sizing import MAX_NOTIONAL_PCT, position_size_usd


@pytest.mark.parametrize("stop", [69300.0, 68600.0, 66500.0])
def test_loss_at_stop_is_exactly_the_risk_budget(stop):
    size = position_size_usd(10_000.0, 70000.0, stop)
    assert size * (70000.0 - stop) / 70000.0 == pytest.approx(100.0, abs=0.01)


def test_tight_stop_is_capped_at_no_leverage():
    size = position_size_usd(10_000.0, 70000.0, 69993.0)  # 0.01% stop -> would be 100x capital
    assert size == 10_000.0 * MAX_NOTIONAL_PCT


@pytest.mark.parametrize("args", [(0.0, 70000.0, 68000.0), (10_000.0, 70000.0, 70000.0), (10_000.0, 70000.0, 71000.0)])
def test_impossible_sizing_returns_none(args):
    assert position_size_usd(*args) is None


def test_paper_and_asama5_use_the_same_function():
    assert paper_trading.position_size_usd is approval.position_size_usd
