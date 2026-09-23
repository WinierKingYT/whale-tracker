from whale_tracker.simulation.sentiment import SentimentSimulator


def _without_timestamp(snapshot: dict) -> dict:
    return {k: v for k, v in snapshot.items() if k != "observed_at"}


def test_seeded_run_is_reproducible():
    # observed_at is real wall-clock time, excluded from comparison --
    # every RNG-driven field (value, label) must still match exactly.
    sim_a = SentimentSimulator(seed=42)
    sim_b = SentimentSimulator(seed=42)
    ticks_a = [_without_timestamp(sim_a.tick()) for _ in range(30)]
    ticks_b = [_without_timestamp(sim_b.tick()) for _ in range(30)]
    assert ticks_a == ticks_b


def test_value_stays_within_bounds():
    sim = SentimentSimulator(seed=1, shock_stddev=20.0)  # large shocks to stress the clamp
    for _ in range(500):
        snapshot = sim.tick()
        assert 0.0 <= snapshot["value"] <= 100.0


def test_label_matches_value_band():
    sim = SentimentSimulator(seed=2)
    for _ in range(200):
        snapshot = sim.tick()
        value, label = snapshot["value"], snapshot["label"]
        if value < 25:
            assert label == "Extreme Fear"
        elif value < 45:
            assert label == "Fear"
        elif value < 55:
            assert label == "Neutral"
        elif value < 75:
            assert label == "Greed"
        else:
            assert label == "Extreme Greed"


def test_snapshot_shape_matches_real_source_contract():
    sim = SentimentSimulator(seed=3)
    snapshot = sim.tick()
    assert set(snapshot.keys()) == {"source", "value", "label", "raw_json", "observed_at"}
    assert snapshot["source"] == "fear_greed"
