"""Offline unit tests: mock the Hermes CLI call, no real subprocess/network."""

import json

import pytest

from whale_tracker.sources import classify


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
