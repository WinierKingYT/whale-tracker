"""Offline unit tests: mock the Claude CLI call, no real subprocess/network."""

import json

import pytest

from whale_tracker.sources import analysis


def _candidate(**overrides):
    base = {
        "direction": "accumulation", "confidence": 0.8,
        "components": {"onchain_flow": 0.4, "funding": 0.25, "sentiment": 0.15, "technical": 0.0},
        "rationale": ["24s net borsa akışı: çıkış $10,000,000"],
    }
    base.update(overrides)
    return base


def _envelope(result: dict) -> str:
    return json.dumps({"is_error": False, "result": json.dumps(result, ensure_ascii=False)})


def test_generate_deep_analysis_parses_valid_response(monkeypatch):
    monkeypatch.setattr(
        analysis, "_call_claude",
        lambda prompt: json.dumps({
            "assessment": "test değerlendirme",
            "counter_argument": "test karşı senaryo",
            "risk_flags": ["flag1"],
            "corroboration_strength": "moderate",
        }, ensure_ascii=False),
    )
    result = analysis.generate_deep_analysis(_candidate(), {})
    assert result["assessment"] == "test değerlendirme"
    assert result["corroboration_strength"] == "moderate"
    assert result["risk_flags"] == ["flag1"]


def test_generate_deep_analysis_rejects_invalid_strength(monkeypatch):
    monkeypatch.setattr(
        analysis, "_call_claude",
        lambda prompt: json.dumps({
            "assessment": "x", "counter_argument": "y", "risk_flags": [],
            "corroboration_strength": "extreme",
        }),
    )
    with pytest.raises(analysis.AnalysisError):
        analysis.generate_deep_analysis(_candidate(), {})


def test_generate_deep_analysis_rejects_non_json(monkeypatch):
    monkeypatch.setattr(analysis, "_call_claude", lambda prompt: "not json at all")
    with pytest.raises(analysis.AnalysisError):
        analysis.generate_deep_analysis(_candidate(), {})


def test_generate_deep_analysis_rejects_missing_fields(monkeypatch):
    monkeypatch.setattr(
        analysis, "_call_claude",
        lambda prompt: json.dumps({"assessment": "x"}),
    )
    with pytest.raises(analysis.AnalysisError):
        analysis.generate_deep_analysis(_candidate(), {})


def test_call_claude_unwraps_result_envelope(monkeypatch):
    class _FakeCompleted:
        returncode = 0
        stdout = _envelope({"assessment": "a", "counter_argument": "b", "risk_flags": [], "corroboration_strength": "weak"})
        stderr = ""

    monkeypatch.setattr(analysis, "_discover_claude", lambda: "/fake/claude")
    monkeypatch.setattr(analysis.subprocess, "run", lambda *a, **k: _FakeCompleted())

    raw = analysis._call_claude("irrelevant prompt")
    parsed = json.loads(raw)
    assert parsed["corroboration_strength"] == "weak"


def test_call_claude_raises_on_error_envelope(monkeypatch):
    class _FakeCompleted:
        returncode = 0
        stdout = json.dumps({"is_error": True, "result": "boom"})
        stderr = ""

    monkeypatch.setattr(analysis, "_discover_claude", lambda: "/fake/claude")
    monkeypatch.setattr(analysis.subprocess, "run", lambda *a, **k: _FakeCompleted())

    with pytest.raises(analysis.AnalysisError):
        analysis._call_claude("irrelevant prompt")


def test_call_claude_raises_when_executable_missing(monkeypatch):
    monkeypatch.setattr(analysis, "_discover_claude", lambda: None)
    with pytest.raises(analysis.AnalysisError):
        analysis._call_claude("irrelevant prompt")
