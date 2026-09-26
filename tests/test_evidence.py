"""WT-05.1 P0: stale or missing critical evidence => explicit ABSTAIN."""

from datetime import UTC, datetime, timedelta

from whale_tracker import observe
from whale_tracker.evidence import MAX_EVIDENCE_AGE, freshness_problems
from whale_tracker.signal import generate_candidates
from whale_tracker.sources.binance import BinanceMarketDataError
from whale_tracker.storage import Storage

NOW = datetime(2026, 9, 25, 12, 0, tzinfo=UTC)


def _market(at):
    return {"symbol": "BTCUSDT", "funding_rate": -0.0005, "open_interest": 1.0, "mark_price": 90000.0,
            "observed_at": at.isoformat()}


def _technical(at):
    return {"symbol": "BTCUSDT", "current_price": 90000.0, "support": 85000.0, "resistance": 95000.0,
            "sma": 88000.0, "trend": "yükseliş", "volatility_daily_stddev": 0.02, "distance_to_support_pct": 5.0,
            "is_above_support": True, "is_near_support": False, "distance_to_resistance_pct": 5.0,
            "is_near_resistance": False, "observed_at": at.isoformat()}


def _seed_strong_accumulation(db, *, market_at, technical_at=None):
    db.insert_market_snapshot(_market(market_at))
    if technical_at:
        db.insert_technical_snapshot(_technical(technical_at))
    db.insert_sentiment_snapshot({"source": "fear_greed", "value": 20.0, "label": "Extreme Fear",
                                  "raw_json": {}, "observed_at": NOW.isoformat()})
    db.insert_onchain_event({
        "tx_hash": "0x1", "log_index": 0, "block_number": 1, "token": "USDT", "from_address": "0xa",
        "to_address": "0xb", "amount_usd_estimate": 50e6, "raw_amount": "1", "from_known_exchange": "binance",
        "to_known_exchange": None, "from_entity_type": "exchange", "to_entity_type": None,
        "observed_at": (NOW - timedelta(hours=1)).isoformat(),
    })


def test_fresh_evidence_has_no_problems(tmp_path):
    with Storage(tmp_path / "e.db") as db:
        _seed_strong_accumulation(db, market_at=NOW, technical_at=NOW)
        assert freshness_problems(db, "BTCUSDT", now=NOW) == []
        assert generate_candidates(db, symbol="BTCUSDT", now=NOW)  # control: evidence does produce a candidate


def test_stale_market_abstains(tmp_path):
    with Storage(tmp_path / "e.db") as db:
        _seed_strong_accumulation(db, market_at=NOW - MAX_EVIDENCE_AGE - timedelta(minutes=1))
        assert any("market" in p for p in freshness_problems(db, "BTCUSDT", now=NOW))
        assert generate_candidates(db, symbol="BTCUSDT", now=NOW) == []


def test_stale_technical_abstains_even_when_market_is_fresh(tmp_path):
    with Storage(tmp_path / "e.db") as db:
        _seed_strong_accumulation(db, market_at=NOW, technical_at=NOW - timedelta(hours=3))
        assert any("technical" in p for p in freshness_problems(db, "BTCUSDT", now=NOW))
        assert generate_candidates(db, symbol="BTCUSDT", now=NOW) == []


def test_missing_market_abstains(tmp_path):
    with Storage(tmp_path / "e.db") as db:
        assert freshness_problems(db, "BTCUSDT", now=NOW) == ["market verisi yok"]


def test_observer_abstains_when_this_cycles_fetch_fails_even_if_db_snapshot_is_recent(tmp_path, monkeypatch):
    """The failure mode we're closing: Binance down -> DB fallback -> signal."""
    db_path = tmp_path / "o.db"
    real_now = datetime.now(UTC)
    with Storage(db_path) as db:
        for symbol in observe.TRACKED_SYMBOLS:
            db.insert_market_snapshot(_market(real_now) | {"symbol": symbol})
            db.insert_technical_snapshot(_technical(real_now) | {"symbol": symbol})

    def down(symbol):
        raise BinanceMarketDataError("down")

    calls = []
    monkeypatch.setattr(observe, "fetch_market_snapshot", down)
    monkeypatch.setattr(observe, "fetch_technical_snapshot", lambda s: _technical(datetime.now(UTC)) | {"symbol": s})
    monkeypatch.setattr(observe, "fetch_fear_greed", lambda: {"source": "fear_greed", "value": 20.0, "label": "x",
                                                              "raw_json": {}, "observed_at": real_now.isoformat()})
    monkeypatch.setattr(observe, "scan_new_transfers", lambda db, min_usd: [])
    monkeypatch.setattr(observe, "fetch_headlines", list)
    monkeypatch.setattr(observe, "notify_after_cycle", lambda *a, **k: None)
    monkeypatch.setattr(observe, "generate_candidates", lambda *a, **k: calls.append(a) or [])

    report = observe.run_once(db_path)
    assert calls == []  # never even asked for a candidate
    assert "ABSTAIN" in report and "market verisi bu döngüde alınamadı" in report
