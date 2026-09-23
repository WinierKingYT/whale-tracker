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
