from whale_tracker.simulation.market import MarketSimulator


def _without_timestamp(snapshot: dict) -> dict:
    return {k: v for k, v in snapshot.items() if k != "observed_at"}


def test_seeded_run_is_reproducible():
    # observed_at is real wall-clock time (when this test happened to
    # run), not simulated -- excluded here since it's expected to differ
    # by microseconds between two independently constructed instances;
    # every RNG-driven field must still match exactly.
    sim_a = MarketSimulator("BTCUSDT", seed=42)
    sim_b = MarketSimulator("BTCUSDT", seed=42)
    for _ in range(20):
        sim_a.tick()
        sim_b.tick()
    assert _without_timestamp(sim_a.market_snapshot()) == _without_timestamp(sim_b.market_snapshot())


def test_different_seeds_diverge():
    sim_a = MarketSimulator("BTCUSDT", seed=1)
    sim_b = MarketSimulator("BTCUSDT", seed=2)
    for _ in range(20):
        sim_a.tick()
        sim_b.tick()
    assert sim_a.market_snapshot()["mark_price"] != sim_b.market_snapshot()["mark_price"]


def test_market_snapshot_shape_matches_real_source():
    sim = MarketSimulator("BTCUSDT", seed=1)
    sim.tick()
    snapshot = sim.market_snapshot()
    assert set(snapshot.keys()) == {"symbol", "funding_rate", "open_interest", "mark_price", "observed_at"}
    assert snapshot["mark_price"] > 0


def test_technical_snapshot_uses_real_compute_technical_snapshot_shape():
    sim = MarketSimulator("BTCUSDT", seed=1, start_price=70000.0)
    for _ in range(200):  # enough ticks to roll several simulated days
        sim.tick()
    snapshot = sim.technical_snapshot()
    assert snapshot["symbol"] == "BTCUSDT"
    assert snapshot["support"] <= snapshot["current_price"] or not snapshot["is_above_support"]
    assert snapshot["trend"] in {"yükseliş", "düşüş", "yatay"}
    assert snapshot["resistance"] >= snapshot["support"]


def test_price_stays_positive_over_many_ticks():
    sim = MarketSimulator("BTCUSDT", seed=7, start_price=100.0, daily_volatility=0.5)
    for _ in range(500):
        sim.tick()
        assert sim.market_snapshot()["mark_price"] > 0
