"""Offline unit tests: mock the Hermes CLI call, no real subprocess/network."""

import json
from datetime import UTC, datetime, timedelta

import pytest

from whale_tracker.sources import classify


class _FakeStorage:
    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows

    def recent_ai_calls(self, call_type: str, *, limit: int) -> list[dict]:
        return self._rows[:limit]


def _event(**overrides):
    base = {
        "tx_hash": "0xabc", "log_index": 0, "token": "USDT", "amount_usd_estimate": 1_000_000.0,
        "from_known_exchange": None, "to_known_exchange": None,
    }
    base.update(overrides)
    return base


def test_classify_event_parses_valid_response(monkeypatch):
    monkeypatch.setattr(
        classify, "_call_hermes",
        lambda prompt: json.dumps({"significance": "high", "interpretation": "test yorum", "confidence": 0.9}),
    )
    result = classify.classify_event(_event())
    assert result == {"significance": "high", "interpretation": "test yorum", "confidence": 0.9}


def test_classify_event_rejects_invalid_significance(monkeypatch):
    monkeypatch.setattr(
        classify, "_call_hermes",
        lambda prompt: json.dumps({"significance": "extreme", "interpretation": "x", "confidence": 0.5}),
    )
    with pytest.raises(classify.ClassificationError):
        classify.classify_event(_event())


def test_classify_event_rejects_non_json(monkeypatch):
    monkeypatch.setattr(classify, "_call_hermes", lambda prompt: "not json at all")
    with pytest.raises(classify.ClassificationError):
        classify.classify_event(_event())


def test_classify_top_events_only_classifies_largest_n_and_skips_failures(monkeypatch):
    events = [_event(amount_usd_estimate=amount) for amount in (1_000_000, 5_000_000, 500_000, 9_000_000)]

    def fake_classify(event):
        if event["amount_usd_estimate"] == 5_000_000:
            raise classify.ClassificationError("boom")
        return {"significance": "medium", "interpretation": "ok", "confidence": 0.5}

    monkeypatch.setattr(classify, "classify_event", fake_classify)

    results = classify.classify_top_events(events, limit=2)
    # top 2 by amount are index 3 ($9M) and index 1 ($5M); index 1 fails and is skipped
    assert set(results.keys()) == {3}


def _failed_call(minutes_ago: float) -> dict:
    called_at = (datetime.now(UTC) - timedelta(minutes=minutes_ago)).isoformat()
    return {"call_type": "kademe1_hermes", "attempted": 5, "succeeded": 0, "called_at": called_at}


def test_circuit_stays_closed_with_too_few_logged_cycles():
    storage = _FakeStorage([_failed_call(5), _failed_call(20)])  # only 2, threshold is 3
    assert classify.kademe1_circuit_open(storage) is False


def test_circuit_stays_closed_if_any_recent_cycle_succeeded():
    rows = [_failed_call(5), {**_failed_call(20), "succeeded": 2}, _failed_call(35)]
    storage = _FakeStorage(rows)
    assert classify.kademe1_circuit_open(storage) is False


def test_circuit_opens_after_threshold_consecutive_failures_within_cooldown():
    storage = _FakeStorage([_failed_call(5), _failed_call(20), _failed_call(35)])
    assert classify.kademe1_circuit_open(storage) is True


def test_circuit_closes_again_once_cooldown_elapses():
    storage = _FakeStorage([_failed_call(45), _failed_call(60), _failed_call(75)])
    assert classify.kademe1_circuit_open(storage) is False


def test_call_hermes_falls_back_to_stdout_when_stderr_empty_on_failure(monkeypatch, tmp_path):
    hermes_path = tmp_path / "hermes.exe"
    hermes_path.write_text("")

    class _FakeCompleted:
        returncode = 1
        stdout = "some diagnostic detail on stdout"
        stderr = ""

    monkeypatch.setattr(classify, "_HERMES_PATH", str(hermes_path))
    monkeypatch.setattr(classify, "run_hidden_and_reap", lambda *a, **k: _FakeCompleted())

    with pytest.raises(classify.ClassificationError, match="some diagnostic detail on stdout"):
        classify._call_hermes("irrelevant prompt")


def test_call_hermes_reports_no_output_when_both_streams_empty(monkeypatch, tmp_path):
    hermes_path = tmp_path / "hermes.exe"
    hermes_path.write_text("")

    class _FakeCompleted:
        returncode = 1
        stdout = ""
        stderr = ""

    monkeypatch.setattr(classify, "_HERMES_PATH", str(hermes_path))
    monkeypatch.setattr(classify, "run_hidden_and_reap", lambda *a, **k: _FakeCompleted())

    with pytest.raises(classify.ClassificationError, match=r"\(çıktı yok\)"):
        classify._call_hermes("irrelevant prompt")
