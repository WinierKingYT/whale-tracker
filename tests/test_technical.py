"""Offline unit tests: mock the HTTP layer, no real network calls."""

from whale_tracker.sources import _retry, technical
from whale_tracker.storage import Storage


class _FakeResponse:
    def __init__(self, payload) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        pass

    def json(self):
        return self._payload


def _candle(open_, high, low, close):
    return [0, str(open_), str(high), str(low), str(close), "0", 0, "0", 0, "0", "0", "0"]


def test_uptrend_above_support(monkeypatch):
    # closes rising steadily: sma will be below the last close -> "yükseliş"
    klines = [_candle(100, 105, 95, 100 + i) for i in range(10)]

    monkeypatch.setattr(
        technical.requests, "get",
        lambda url, params=None, timeout=None: _FakeResponse(klines),
    )

    snap = technical.fetch_technical_snapshot("BTCUSDT", lookback_days=10)

    assert snap["trend"] == "yükseliş"
    assert snap["support"] == 95.0
    assert snap["resistance"] == 105.0
    assert snap["is_above_support"] is True
    assert snap["current_price"] == 109.0  # last close: 100 + 9


def test_near_support_flag(monkeypatch):
    # flat prices around 100, one low dip to 98 sets support; last close at 100
    klines = [_candle(100, 101, 100, 100) for _ in range(9)] + [_candle(100, 101, 98, 100)]

    monkeypatch.setattr(
        technical.requests, "get",
        lambda url, params=None, timeout=None: _FakeResponse(klines),
    )

    snap = technical.fetch_technical_snapshot("BTCUSDT", lookback_days=10)

    assert snap["support"] == 98.0
    assert snap["is_above_support"] is True
    assert snap["is_near_support"] is True  # (100-98)/98 ≈ 2% <= 3% threshold


def test_snapshot_round_trips_through_storage(monkeypatch, tmp_path):
    """Regression test: a real end-to-end run once failed here with
    sqlite3.ProgrammingError because fetch_technical_snapshot() didn't
    include "observed_at" -- the per-field unit tests above never caught
    it since they check individual dict keys, not the actual storage
    write path. Caught by running the real pipeline, not by a unit test;
    this test exists so it can't regress silently again."""
    klines = [_candle(100, 105, 95, 100 + i) for i in range(10)]
    monkeypatch.setattr(
        technical.requests, "get",
        lambda url, params=None, timeout=None: _FakeResponse(klines),
    )
    snap = technical.fetch_technical_snapshot("BTCUSDT", lookback_days=10)

    with Storage(tmp_path / "t.db") as db:
        db.insert_technical_snapshot(snap)  # must not raise
        stored = db.latest_technical_snapshot("BTCUSDT")

    assert stored["trend"] == "yükseliş"


def test_raises_on_http_error(monkeypatch):
    monkeypatch.setattr(_retry.time, "sleep", lambda *a: None)  # skip real backoff delay

    def raise_error(url, params=None, timeout=None):
        raise technical.requests.RequestException("network down")

    monkeypatch.setattr(technical.requests, "get", raise_error)

    try:
        technical.fetch_technical_snapshot("BTCUSDT")
        assert False, "expected TechnicalDataError"
    except technical.TechnicalDataError:
        pass
