from whale_tracker.simulation.onchain import OnchainSimulator


def _without_timestamps(events: list[dict]) -> list[dict]:
    return [{k: v for k, v in e.items() if k != "observed_at"} for e in events]


def test_seeded_run_is_reproducible():
    # observed_at is real wall-clock time (both simulators call
    # tick_events() in the same test, microseconds apart), excluded from
    # comparison -- every RNG-driven field must still match exactly.
    sim_a = OnchainSimulator(seed=42)
    sim_b = OnchainSimulator(seed=42)
    events_a = [_without_timestamps(sim_a.tick_events()) for _ in range(50)]
    events_b = [_without_timestamps(sim_b.tick_events()) for _ in range(50)]
    assert events_a == events_b


def test_events_respect_min_usd_threshold():
    sim = OnchainSimulator(seed=1, min_usd=5_000_000.0, events_per_cycle_mean=3.0)
    for _ in range(100):
        for event in sim.tick_events():
            assert event["amount_usd_estimate"] >= 5_000_000.0


def test_event_shape_matches_real_source_contract():
    sim = OnchainSimulator(seed=3, events_per_cycle_mean=5.0, min_usd=1.0)
    events = []
    for _ in range(20):
        events.extend(sim.tick_events())
    assert events  # a high mean + low threshold should produce at least one
    event = events[0]
    assert set(event.keys()) == {
        "tx_hash", "log_index", "block_number", "token", "from_address", "to_address",
        "amount_usd_estimate", "raw_amount", "from_known_exchange", "to_known_exchange", "observed_at",
    }
    assert event["token"] in {"USDT", "USDC"}


def test_some_events_hit_known_wallets_over_many_cycles():
    sim = OnchainSimulator(seed=5, events_per_cycle_mean=5.0, min_usd=1.0)
    events = []
    for _ in range(100):
        events.extend(sim.tick_events())
    known_hits = [e for e in events if e["from_known_exchange"] or e["to_known_exchange"]]
    assert known_hits  # real known-exchange-wallets.json addresses should surface sometimes


def test_tx_hashes_are_unique():
    sim = OnchainSimulator(seed=9, events_per_cycle_mean=4.0, min_usd=1.0)
    hashes = [e["tx_hash"] for _ in range(50) for e in sim.tick_events()]
    assert len(hashes) == len(set(hashes))
