"""Offline unit tests: mock the HTTP layer, no real network calls."""

import pytest

from whale_tracker.sources import _retry, sentiment


class _FakeResponse:
    def __init__(self, payload, status: int = 200) -> None:
        self._payload = payload
        self.status_code = status

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise sentiment.requests.HTTPError("bad status")

    def json(self):
        return self._payload


def test_fetch_fear_greed_parses_value_and_label(monkeypatch):
    monkeypatch.setattr(
        sentiment.requests, "get",
        lambda url, params=None, timeout=None: _FakeResponse(
            {"data": [{"value": "71", "value_classification": "Greed"}]}
        ),
    )
    result = sentiment.fetch_fear_greed()
    assert result["source"] == "fear_greed"
    assert result["value"] == 71.0
    assert result["label"] == "Greed"


def test_unexpected_response_shape_raises(monkeypatch):
    monkeypatch.setattr(_retry.time, "sleep", lambda *a: None)
    monkeypatch.setattr(sentiment.requests, "get", lambda url, params=None, timeout=None: _FakeResponse({}))

    with pytest.raises(sentiment.FearGreedError):
        sentiment.fetch_fear_greed()


def test_network_error_is_retried_then_raised(monkeypatch):
    monkeypatch.setattr(_retry.time, "sleep", lambda *a: None)
    calls = {"n": 0}

    def fake_get(url, params=None, timeout=None):
        calls["n"] += 1
        raise sentiment.requests.RequestException("network down")

    monkeypatch.setattr(sentiment.requests, "get", fake_get)

    with pytest.raises(sentiment.FearGreedError):
        sentiment.fetch_fear_greed()
    assert calls["n"] == _retry.DEFAULT_RETRIES
