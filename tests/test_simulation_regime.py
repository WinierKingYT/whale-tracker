from datetime import UTC, datetime, timedelta

from whale_tracker.simulation.market import MarketSimulator
from whale_tracker.simulation.onchain import OnchainSimulator
from whale_tracker.simulation.regime import LatentRegime

T0 = datetime(2026, 9, 1, tzinfo=UTC)


def test_regime_is_deterministic_regardless_of_query_pattern():
    """Two simulators query the same regime at different moments in a
    cycle; the value at a given time must not depend on who asked first."""
    stepwise = LatentRegime(seed=3)
    for i in range(200):
        stepwise.value_at(T0 + timedelta(minutes=15 * i))
    jumped = LatentRegime(seed=3)
    jumped.value_at(T0)
    assert jumped.value_at(T0 + timedelta(minutes=15 * 199)) == stepwise.value_at(T0 + timedelta(minutes=15 * 199))


def test_regime_stays_bounded_and_actually_moves():
    regime = LatentRegime(seed=1)
    values = [regime.value_at(T0 + timedelta(minutes=15 * i)) for i in range(5000)]
    assert all(-1.0 <= v <= 1.0 for v in values)
    assert max(values) - min(values) > 0.3


def test_market_without_regime_is_unchanged_by_the_new_parameters():
    plain = MarketSimulator("BTCUSDT", seed=5)
    explicit_off = MarketSimulator("BTCUSDT", seed=5, regime=None, edge_daily_drift=0.02)
    for _ in range(100):
        plain.tick()
        explicit_off.tick()
    assert plain.market_snapshot()["mark_price"] == explicit_off.market_snapshot()["mark_price"]


class _FixedRegime:
    def __init__(self, value: float) -> None:
        self.value = value

    def value_at(self, _moment: datetime) -> float:
        return self.value


def test_positive_regime_drifts_price_up_negative_down():
    up = MarketSimulator("BTCUSDT", seed=5, regime=_FixedRegime(1.0), edge_daily_drift=0.05)
    down = MarketSimulator("BTCUSDT", seed=5, regime=_FixedRegime(-1.0), edge_daily_drift=0.05)
    for _ in range(96 * 10):
        up.tick()
        down.tick()
    assert up.market_snapshot()["mark_price"] > down.market_snapshot()["mark_price"]


def test_positive_regime_tilts_flow_toward_exchange_outflows():
    sim = OnchainSimulator(seed=2, events_per_cycle_mean=5.0, min_usd=1.0, regime=_FixedRegime(1.0), flow_bias=1.0)
    events = [e for i in range(50) for e in sim.tick_events(observed_at=(T0 + timedelta(minutes=15 * i)).isoformat())]
    assert events
    outflows = sum(1 for e in events if e["from_known_exchange"] and not e["to_known_exchange"])
    inflows = sum(1 for e in events if e["to_known_exchange"] and not e["from_known_exchange"])
    assert outflows > inflows * 3
