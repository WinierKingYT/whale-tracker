"""Offline unit tests: mock the HTTP layer, no real network calls."""

import pytest

from whale_tracker.sources import _retry, binance


class _FakeResponse:
    def __init__(self, payload, status: int = 200) -> None:
        self._payload = payload
        self.status_code = status

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise binance.requests.HTTPError("bad status")

    def json(self):
        return self._payload


def test_fetch_market_snapshot_combines_both_endpoints(monkeypatch):
    def fake_get(url, params=None, timeout=None):
        if "premiumIndex" in url:
            return _FakeResponse({"lastFundingRate": "0.0001", "markPrice": "70000.5"})
        return _FakeResponse({"openInterest": "12345.6"})

    monkeypatch.setattr(binance.requests, "get", fake_get)

    snapshot = binance.fetch_market_snapshot("BTCUSDT")
    assert snapshot["symbol"] == "BTCUSDT"
    assert snapshot["funding_rate"] == 0.0001
    assert snapshot["mark_price"] == 70000.5
    assert snapshot["open_interest"] == 12345.6


def test_unexpected_response_shape_raises_without_retrying_forever(monkeypatch):
    monkeypatch.setattr(_retry.time, "sleep", lambda *a: None)
    monkeypatch.setattr(binance.requests, "get", lambda url, params=None, timeout=None: _FakeResponse({}))

    with pytest.raises(binance.BinanceMarketDataError):
        binance.fetch_market_snapshot("BTCUSDT")


def test_network_error_is_retried_then_raised(monkeypatch):
    monkeypatch.setattr(_retry.time, "sleep", lambda *a: None)
    calls = {"n": 0}

    def fake_get(url, params=None, timeout=None):
        calls["n"] += 1
        raise binance.requests.RequestException("network down")

    monkeypatch.setattr(binance.requests, "get", fake_get)

    with pytest.raises(binance.BinanceMarketDataError):
        binance.fetch_market_snapshot("BTCUSDT")
    assert calls["n"] == _retry.DEFAULT_RETRIES  # retried before giving up, not just one attempt


def test_network_error_recovers_on_a_later_retry(monkeypatch):
    monkeypatch.setattr(_retry.time, "sleep", lambda *a: None)
    calls = {"n": 0}

    def fake_get(url, params=None, timeout=None):
        calls["n"] += 1
        if calls["n"] == 1:
            raise binance.requests.RequestException("transient")
        if "premiumIndex" in url:
            return _FakeResponse({"lastFundingRate": "0.0001", "markPrice": "70000.5"})
        return _FakeResponse({"openInterest": "12345.6"})

    monkeypatch.setattr(binance.requests, "get", fake_get)

    snapshot = binance.fetch_market_snapshot("BTCUSDT")
    assert snapshot["mark_price"] == 70000.5
