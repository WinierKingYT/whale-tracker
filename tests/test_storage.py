from datetime import UTC, datetime

from whale_tracker.storage import Storage


def _now() -> str:
    return datetime.now(UTC).isoformat()


def test_insert_onchain_event_and_dedup(tmp_path):
    with Storage(tmp_path / "test.db") as db:
        event = {
            "tx_hash": "0xabc", "log_index": 0, "block_number": 100, "token": "USDT",
            "from_address": "0x1", "to_address": "0x2", "amount_usd_estimate": 1_000_000.0,
            "raw_amount": "1000000000000", "from_known_exchange": None, "to_known_exchange": "binance",
            "observed_at": _now(),
        }
        assert db.insert_onchain_event(event) is True
        assert db.insert_onchain_event(event) is False  # duplicate, same tx_hash+log_index

        events = db.recent_onchain_events()
        assert len(events) == 1
        assert events[0]["to_known_exchange"] == "binance"


def test_scan_cursor_roundtrip(tmp_path):
    with Storage(tmp_path / "test.db") as db:
        assert db.get_scan_cursor("ethereum") is None
        db.set_scan_cursor("ethereum", 12345, _now())
        assert db.get_scan_cursor("ethereum") == 12345
        db.set_scan_cursor("ethereum", 12400, _now())
        assert db.get_scan_cursor("ethereum") == 12400


def test_technical_snapshot(tmp_path):
    with Storage(tmp_path / "test.db") as db:
        assert db.latest_technical_snapshot("BTCUSDT") is None
        db.insert_technical_snapshot({
            "symbol": "BTCUSDT", "current_price": 85000.0, "support": 75000.0,
            "resistance": 88000.0, "sma": 80000.0, "trend": "yükseliş",
            "volatility_daily_stddev": 0.02, "distance_to_support_pct": 0.13,
            "is_above_support": True, "is_near_support": False,
            "distance_to_resistance_pct": 0.034, "is_near_resistance": True,
            "observed_at": _now(),
        })
        snap = db.latest_technical_snapshot("BTCUSDT")
        assert snap["trend"] == "yükseliş"
        assert snap["is_above_support"] is True
        assert snap["is_near_support"] is False


def test_market_snapshot(tmp_path):
    with Storage(tmp_path / "test.db") as db:
        assert db.latest_market_snapshot("BTCUSDT") is None
        db.insert_market_snapshot({
            "symbol": "BTCUSDT", "funding_rate": 0.0001, "open_interest": 123456.0,
            "mark_price": 65000.0, "observed_at": _now(),
        })
        snap = db.latest_market_snapshot("BTCUSDT")
        assert snap["symbol"] == "BTCUSDT"
        assert snap["funding_rate"] == 0.0001


def test_sentiment_snapshot(tmp_path):
    with Storage(tmp_path / "test.db") as db:
        db.insert_sentiment_snapshot({
            "source": "fear_greed", "value": 72.0, "label": "Greed",
            "raw_json": {"raw": "data"}, "observed_at": _now(),
        })
        snap = db.latest_sentiment_snapshot("fear_greed")
        assert snap["value"] == 72.0
        assert snap["label"] == "Greed"


def test_signal_candidate_insert_returns_id_and_deep_analysis_links_to_it(tmp_path):
    with Storage(tmp_path / "test.db") as db:
        candidate_id = db.insert_signal_candidate({
            "direction": "accumulation", "confidence": 0.8,
            "components": {"onchain_flow": 0.4}, "rationale": ["test"],
            "generated_at": _now(),
        })
        assert isinstance(candidate_id, int)

        db.insert_deep_analysis(candidate_id, {
            "assessment": "test değerlendirme", "counter_argument": "test karşı",
            "risk_flags": ["flag1"], "corroboration_strength": "moderate",
        }, _now())

        row = db._conn.execute(
            "SELECT * FROM deep_analyses WHERE signal_candidate_id = ?", (candidate_id,)
        ).fetchone()
        assert row["assessment"] == "test değerlendirme"
        assert row["corroboration_strength"] == "moderate"


def test_final_proposal_links_to_signal_candidate(tmp_path):
    with Storage(tmp_path / "test.db") as db:
        candidate_id = db.insert_signal_candidate({
            "direction": "accumulation", "confidence": 0.9,
            "components": {}, "rationale": [], "generated_at": _now(),
        })
        db.insert_final_proposal(candidate_id, {
            "action": "long_candidate", "reason": None,
            "max_position_size_pct": 0.01, "stop_loss_price": 68600.0,
            "entry_rationale": "test rationale", "worst_case_scenario": "test worst case",
            "counter_arguments": ["a", "b"], "conviction": "high",
        }, _now())

        row = db._conn.execute(
            "SELECT * FROM final_proposals WHERE signal_candidate_id = ?", (candidate_id,)
        ).fetchone()
        assert row["action"] == "long_candidate"
        assert row["stop_loss_price"] == 68600.0
        assert row["conviction"] == "high"


def test_ai_call_log_summary_aggregates_by_call_type(tmp_path):
    with Storage(tmp_path / "test.db") as db:
        db.insert_ai_call_log(
            "kademe2_sonnet", attempted=1, succeeded=1, duration_ms=1000.0,
            error_reason=None, called_at=_now(),
        )
        db.insert_ai_call_log(
            "kademe2_sonnet", attempted=1, succeeded=0, duration_ms=500.0,
            error_reason="rate limited", called_at=_now(),
        )
        db.insert_ai_call_log(
            "kademe1_hermes", attempted=5, succeeded=5, duration_ms=8000.0,
            error_reason=None, called_at=_now(),
        )

        summary = {row["call_type"]: row for row in db.ai_call_log_summary()}

    assert summary["kademe2_sonnet"]["cycles"] == 2
    assert summary["kademe2_sonnet"]["attempted"] == 2
    assert summary["kademe2_sonnet"]["succeeded"] == 1
    assert summary["kademe2_sonnet"]["failed_cycles"] == 1
    assert summary["kademe2_sonnet"]["avg_duration_ms"] == 750.0
    assert summary["kademe1_hermes"]["attempted"] == 5
    assert summary["kademe1_hermes"]["failed_cycles"] == 0


def test_ai_call_log_summary_empty_by_default(tmp_path):
    with Storage(tmp_path / "test.db") as db:
        assert db.ai_call_log_summary() == []


def test_recent_ai_calls_returns_newest_first_limited_and_filtered_by_type(tmp_path):
    with Storage(tmp_path / "test.db") as db:
        db.insert_ai_call_log(
            "kademe1_hermes", attempted=5, succeeded=0, duration_ms=100.0,
            error_reason="429", called_at="2026-09-24T10:00:00+00:00",
        )
        db.insert_ai_call_log(
            "kademe2_sonnet", attempted=1, succeeded=1, duration_ms=100.0,
            error_reason=None, called_at="2026-09-24T10:05:00+00:00",
        )
        db.insert_ai_call_log(
            "kademe1_hermes", attempted=5, succeeded=0, duration_ms=100.0,
            error_reason="429", called_at="2026-09-24T10:15:00+00:00",
        )

        recent = db.recent_ai_calls("kademe1_hermes", limit=1)

    assert len(recent) == 1
    assert recent[0]["called_at"] == "2026-09-24T10:15:00+00:00"


# --- WT-05.1 P1: price_and_levels_history pairs strictly within one cycle ---

def _pairing_db(tmp_path, market_minutes, technical_minutes):
    from datetime import UTC, datetime, timedelta

    base = datetime(2026, 9, 25, 12, 0, tzinfo=UTC)
    db = Storage(tmp_path / "pair.db")
    for m in market_minutes:
        db.insert_market_snapshot({"symbol": "BTCUSDT", "funding_rate": 0.0, "open_interest": 1.0,
                                   "mark_price": 100.0 + m, "observed_at": (base + timedelta(minutes=m)).isoformat()})
    for m in technical_minutes:
        db.insert_technical_snapshot({
            "symbol": "BTCUSDT", "current_price": 100.0, "support": 90.0 + m, "resistance": 110.0 + m, "sma": 100.0,
            "trend": "yatay", "volatility_daily_stddev": 0.01, "distance_to_support_pct": 0.1,
            "is_above_support": True, "is_near_support": False, "distance_to_resistance_pct": 0.1,
            "is_near_resistance": False, "observed_at": (base + timedelta(minutes=m)).isoformat(),
        })
    return db


def test_pairing_uses_the_technical_fetched_just_after_the_market(tmp_path):
    with _pairing_db(tmp_path, [0, 15], [0.03, 15.03]) as db:
        rows = db.price_and_levels_history("BTCUSDT")
    assert [r["support"] for r in rows] == [90.03, 105.03]


def test_previous_cycles_technical_is_never_paired(tmp_path):
    """Cycle at 15: technical fetch failed, so the only earlier one is cycle 0's."""
    with _pairing_db(tmp_path, [0, 15], [0.03]) as db:
        rows = db.price_and_levels_history("BTCUSDT")
    assert [r["mark_price"] for r in rows] == [100.0]  # the 15-min market row is dropped, not paired with 0.03


def test_technical_outside_the_same_cycle_window_is_not_paired(tmp_path):
    with _pairing_db(tmp_path, [0], [10]) as db:  # 10 min later = next-cycle territory
        assert db.price_and_levels_history("BTCUSDT") == []


def test_one_technical_pairs_with_at_most_one_market(tmp_path):
    with _pairing_db(tmp_path, [0, 1], [2]) as db:
        rows = db.price_and_levels_history("BTCUSDT")
    assert len(rows) == 1
