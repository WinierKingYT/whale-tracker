import pytest
import requests

from whale_tracker.sources import _retry


def test_returns_immediately_on_first_success(monkeypatch):
    monkeypatch.setattr(_retry.time, "sleep", lambda *a: None)
    calls = []

    def fn():
        calls.append(1)
        return "ok"

    assert _retry.get_with_retries(fn) == "ok"
    assert len(calls) == 1


def test_retries_and_succeeds_on_a_later_attempt(monkeypatch):
    sleeps = []
    monkeypatch.setattr(_retry.time, "sleep", lambda s: sleeps.append(s))
    calls = {"n": 0}

    def fn():
        calls["n"] += 1
        if calls["n"] < 3:
            raise requests.RequestException("transient")
        return "ok"

    assert _retry.get_with_retries(fn) == "ok"
    assert calls["n"] == 3
    assert sleeps == [2, 4]  # linear backoff between attempts 1->2 and 2->3


def test_raises_the_last_error_after_exhausting_retries(monkeypatch):
    monkeypatch.setattr(_retry.time, "sleep", lambda *a: None)
    calls = {"n": 0}

    def fn():
        calls["n"] += 1
        raise requests.RequestException(f"fail {calls['n']}")

    with pytest.raises(requests.RequestException, match="fail 3"):
        _retry.get_with_retries(fn)
    assert calls["n"] == 3  # DEFAULT_RETRIES


def test_respects_a_custom_retries_count(monkeypatch):
    monkeypatch.setattr(_retry.time, "sleep", lambda *a: None)
    calls = {"n": 0}

    def fn():
        calls["n"] += 1
        raise requests.RequestException("fail")

    with pytest.raises(requests.RequestException):
        _retry.get_with_retries(fn, retries=1)
    assert calls["n"] == 1


def test_does_not_retry_non_request_exceptions(monkeypatch):
    monkeypatch.setattr(_retry.time, "sleep", lambda *a: None)
    calls = {"n": 0}

    def fn():
        calls["n"] += 1
        raise ValueError("not a network error")

    with pytest.raises(ValueError):
        _retry.get_with_retries(fn)
    assert calls["n"] == 1
