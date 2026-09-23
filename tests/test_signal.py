from datetime import UTC, datetime, timedelta

from whale_tracker import signal
from whale_tracker.storage import Storage


def _now_iso(hours_ago: float = 0) -> str:
    return (datetime.now(UTC) - timedelta(hours=hours_ago)).isoformat()


def _seed_outflow_event(db, *, amount, hours_ago=1):
    db.insert_onchain_event({
        "tx_hash": f"0x{hours_ago}-{amount}", "log_index": 0, "block_number": 1, "token": "USDT",
        "from_address": "0xexchange", "to_address": "0xuser", "amount_usd_estimate": amount,
        "raw_amount": "1", "from_known_exchange": "binance", "to_known_exchange": None,
        "observed_at": _now_iso(hours_ago),
    })


def _seed_inflow_event(db, *, amount, hours_ago=1):
    db.insert_onchain_event({
        "tx_hash": f"0xin-{hours_ago}-{amount}", "log_index": 0, "block_number": 1, "token": "USDT",
        "from_address": "0xuser", "to_address": "0xexchange", "amount_usd_estimate": amount,
        "raw_amount": "1", "from_known_exchange": None, "to_known_exchange": "binance",
        "observed_at": _now_iso(hours_ago),
    })


def test_no_market_snapshot_means_no_candidates(tmp_path):
    with Storage(tmp_path / "t.db") as db:
        assert signal.generate_candidates(db) == []


def test_net_outflow_with_neutral_funding_and_no_bad_news_produces_accumulation_candidate(tmp_path):
    with Storage(tmp_path / "t.db") as db:
        db.insert_market_snapshot({
            "symbol": "BTCUSDT", "funding_rate": 0.00005, "open_interest": 100.0,
            "mark_price": 90000.0, "observed_at": _now_iso(),
        })
        db.insert_sentiment_snapshot({
            "source": "fear_greed", "value": 50.0, "label": "Neutral",
            "raw_json": {}, "observed_at": _now_iso(),
        })
        _seed_outflow_event(db, amount=15_000_000)

        candidates = signal.generate_candidates(db)

    directions = {c["direction"] for c in candidates}
    assert "accumulation" in directions
    accumulation = next(c for c in candidates if c["direction"] == "accumulation")
    assert accumulation["confidence"] > 0
    assert accumulation["components"]["technical"] == 0.0
    assert accumulation["confidence"] <= signal._MAX_CONFIDENCE_WITHOUT_TECHNICAL


def test_negative_news_zeroes_out_flow_component_for_accumulation(tmp_path):
    with Storage(tmp_path / "t.db") as db:
        db.insert_market_snapshot({
            "symbol": "BTCUSDT", "funding_rate": 0.00005, "open_interest": 100.0,
            "mark_price": 90000.0, "observed_at": _now_iso(),
        })
        _seed_outflow_event(db, amount=15_000_000)
        db.insert_headline({
            "source": "coindesk", "title": "Major exchange hack drains $200M",
            "link": "https://example.com/x", "published_at": None, "observed_at": _now_iso(),
        })

        candidates = signal.generate_candidates(db)

    accumulation = next(c for c in candidates if c["direction"] == "accumulation")
    assert accumulation["components"]["onchain_flow"] == 0.0
    assert any("olumsuz haber" in line for line in accumulation["rationale"])


def test_old_events_outside_window_are_excluded(tmp_path):
    with Storage(tmp_path / "t.db") as db:
        db.insert_market_snapshot({
            "symbol": "BTCUSDT", "funding_rate": 0.0, "open_interest": 100.0,
            "mark_price": 90000.0, "observed_at": _now_iso(),
        })
        _seed_outflow_event(db, amount=15_000_000, hours_ago=48)  # outside 24h window

        candidates = signal.generate_candidates(db, flow_window_hours=24)

    assert candidates == []  # no flow signal inside the window -> nothing to corroborate
