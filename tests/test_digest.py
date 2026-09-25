"""Offline tests for the daily digest and ntfy notifications -- no network."""

from datetime import UTC, datetime, timedelta

import pytest

from whale_tracker import digest, notify
from whale_tracker.storage import Storage

NOW = datetime(2026, 9, 25, 7, 0, tzinfo=UTC)
LOCAL_MORNING = datetime(2026, 9, 25, 10, 0).astimezone()
LOCAL_NIGHT = datetime(2026, 9, 25, 6, 0).astimezone()
CONFIG = {"ntfy_topic": "t", "ntfy_server": "https://ntfy.example", "daily_digest_hour": 9}


def _iso(minutes_ago: float) -> str:
    return (NOW - timedelta(minutes=minutes_ago)).isoformat()


def _seed(db: Storage, *, latest_minutes_ago: float = 10) -> None:
    db.insert_market_snapshot({"symbol": "BTCUSDT", "funding_rate": 0.0001, "open_interest": 1.0,
                               "mark_price": 100_000.0, "observed_at": _iso(24 * 60 + 5)})
    db.insert_market_snapshot({"symbol": "BTCUSDT", "funding_rate": 0.0001, "open_interest": 1.0,
                               "mark_price": 110_000.0, "observed_at": _iso(latest_minutes_ago)})
    db.insert_sentiment_snapshot({"source": "fear_greed", "value": 30.0, "label": "Fear",
                                  "raw_json": {}, "observed_at": _iso(60)})
    db.insert_onchain_event({
        "tx_hash": "0x1", "log_index": 0, "block_number": 1, "token": "USDT",
        "from_address": "0xa", "to_address": "0xb", "amount_usd_estimate": 5_000_000.0, "raw_amount": "5",
        "from_known_exchange": None, "to_known_exchange": "binance", "observed_at": _iso(30),
    })


def test_compose_digest_summarises_the_last_24h(tmp_path):
    with Storage(tmp_path / "d.db") as db:
        _seed(db)
        text = digest.compose_digest(db, now=NOW)
    assert "BTC $110,000 (+10.0%)" in text
    assert "Fear&Greed: 30 (Fear)" in text
    assert "borsalara net giriş $5.0M" in text
    assert "Gözlemci sağlıklı" in text


def test_compose_digest_warns_when_the_observer_went_quiet(tmp_path):
    with Storage(tmp_path / "d.db") as db:
        _seed(db, latest_minutes_ago=120)
        assert "[UYARI] Son veri 120 dk önce" in digest.compose_digest(db, now=NOW)


def test_digest_due_once_per_local_day_after_the_hour(tmp_path):
    with Storage(tmp_path / "d.db") as db:
        assert digest.digest_due(db, local_now=LOCAL_NIGHT, digest_hour=9) is False
        assert digest.digest_due(db, local_now=LOCAL_MORNING, digest_hour=9) is True
        db.set_scan_cursor(digest.DIGEST_CURSOR, 20260925, NOW.isoformat())
        assert digest.digest_due(db, local_now=LOCAL_MORNING, digest_hour=9) is False
        assert digest.digest_due(db, local_now=LOCAL_MORNING + timedelta(days=1), digest_hour=9) is True


def test_cycle_alerts_cover_proposal_open_and_close():
    candidate = {
        "symbol": "BTCUSDT", "confidence": 0.8,
        "final_proposal": {"action": "long_candidate", "stop_loss_price": 95_000.0, "conviction": "medium"},
        "paper_position": {"symbol": "BTCUSDT", "entry_price": 100_000.0, "stop_loss_price": 95_000.0,
                           "take_profit_price": 108_000.0, "position_size_usd": 100.0},
    }
    closed = {"symbol": "ETHUSDT", "status": "take_profit", "exit_price": 3_000.0, "pnl_pct": 0.05, "pnl_usd": 5.0}
    titles = [title for title, _ in digest.cycle_alerts([candidate, {"symbol": "ETHUSDT", "confidence": 0.3}], [closed])]
    assert titles == ["Kademe 3 önerisi: BTCUSDT", "Kağıt pozisyon açıldı: BTCUSDT", "Kağıt pozisyon kapandı: ETHUSDT"]


def test_notify_after_cycle_sends_digest_once_and_survives_failures(tmp_path, monkeypatch, capsys):
    sent = []
    monkeypatch.setattr(digest, "send", lambda config, title, message, **kw: sent.append(title))
    with Storage(tmp_path / "d.db") as db:
        _seed(db)
        for _ in range(2):
            digest.notify_after_cycle(db, candidates=[], closed_positions=[], now=NOW, local_now=LOCAL_MORNING, config=CONFIG)
        assert len(sent) == 1 and sent[0].startswith("whale-tracker günlük özet")

        def failing_send(*args, **kwargs):
            raise notify.NotifyError("ntfy HTTP 500")

        monkeypatch.setattr(digest, "send", failing_send)
        digest.notify_after_cycle(db, candidates=[], closed_positions=[], now=NOW,
                                  local_now=LOCAL_MORNING + timedelta(days=1), config=CONFIG)
        # Failure is logged, not raised, and the day is NOT marked sent -- next cycle retries.
        assert "bildirim gönderilemedi" in capsys.readouterr().err
        assert digest.digest_due(db, local_now=LOCAL_MORNING + timedelta(days=1), digest_hour=9) is True


def test_notify_after_cycle_is_silent_without_config(tmp_path, monkeypatch):
    monkeypatch.setattr(digest, "send", lambda *a, **k: pytest.fail("must not send without a topic"))
    with Storage(tmp_path / "d.db") as db:
        digest.notify_after_cycle(db, candidates=[], closed_positions=[], now=NOW, local_now=LOCAL_MORNING, config={})


def test_load_config_prefers_environment_and_is_empty_without_topic(tmp_path, monkeypatch):
    monkeypatch.delenv(notify.TOPIC_ENV, raising=False)
    missing = tmp_path / "none.json"
    assert notify.load_config(missing) == {}
    monkeypatch.setenv(notify.TOPIC_ENV, "from-env")
    assert notify.load_config(missing)["ntfy_topic"] == "from-env"


def test_init_config_creates_a_random_topic_once(tmp_path):
    path = tmp_path / "notify-config.json"
    first = notify.init_config(path)
    assert first.startswith("whale-tracker-") and len(first) > 30
    assert notify.init_config(path) == first


def test_send_posts_json_and_raises_notify_error_on_failure(monkeypatch):
    calls = []

    class _Response:
        def __init__(self, ok):
            self.ok, self.status_code, self.text = ok, 200 if ok else 429, "slow down"

    monkeypatch.setattr(notify.requests, "post", lambda url, json, timeout: calls.append((url, json)) or _Response(True))
    notify.send(CONFIG, "Başlık ğüşıöç", "mesaj")
    assert calls[0][0] == "https://ntfy.example"
    assert calls[0][1]["topic"] == "t" and calls[0][1]["title"] == "Başlık ğüşıöç"

    monkeypatch.setattr(notify.requests, "post", lambda url, json, timeout: _Response(False))
    with pytest.raises(notify.NotifyError, match="429"):
        notify.send(CONFIG, "x", "y")
