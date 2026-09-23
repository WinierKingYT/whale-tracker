"""Offline unit tests: mock the Claude CLI call, no real subprocess/network."""

import json

import pytest

from whale_tracker.sources import proposal


def _candidate(**overrides):
    base = {"direction": "accumulation", "confidence": 0.9}
    base.update(overrides)
    return base


def _deep_analysis(**overrides):
    base = {
        "assessment": "test", "counter_argument": "test",
        "risk_flags": [], "corroboration_strength": "strong",
    }
    base.update(overrides)
    return base


def _technical(support=70000.0):
    return {"trend": "yükseliş", "support": support, "current_price": 75000.0}


def test_non_accumulation_direction_is_no_action_without_calling_ai(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("should not call the AI for a distribution candidate")
    monkeypatch.setattr(proposal, "_call_claude", boom)

    result = proposal.generate_final_proposal(
        _candidate(direction="distribution"), _deep_analysis(), {"technical_snapshot": _technical()}
    )
    assert result["action"] == "no_action"
    assert "accumulation" in result["reason"]


def test_missing_technical_snapshot_is_no_action_without_calling_ai(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("should not call the AI without a stop-loss basis")
    monkeypatch.setattr(proposal, "_call_claude", boom)

    result = proposal.generate_final_proposal(_candidate(), _deep_analysis(), {"technical_snapshot": None})
    assert result["action"] == "no_action"
    assert "stop-loss" in result["reason"]


def test_valid_proposal_computes_stop_loss_in_code_not_from_ai(monkeypatch):
    monkeypatch.setattr(
        proposal, "_call_claude",
        lambda prompt, **kw: json.dumps({
            "entry_rationale": "test rationale",
            "worst_case_scenario": "test worst case",
            "counter_arguments": ["a", "b"],
            "conviction": "high",
        }),
    )
    result = proposal.generate_final_proposal(_candidate(), _deep_analysis(), {"technical_snapshot": _technical(support=70000.0)})
    assert result["action"] == "long_candidate"
    assert result["stop_loss_price"] == 70000.0 * (1 - proposal.STOP_LOSS_SUPPORT_BUFFER_PCT)
    assert result["max_position_size_pct"] == proposal.MAX_POSITION_SIZE_PCT
    assert result["conviction"] == "high"
    assert result["counter_arguments"] == ["a", "b"]


def test_invalid_conviction_raises(monkeypatch):
    monkeypatch.setattr(
        proposal, "_call_claude",
        lambda prompt, **kw: json.dumps({
            "entry_rationale": "x", "worst_case_scenario": "y",
            "counter_arguments": [], "conviction": "extreme",
        }),
    )
    with pytest.raises(proposal.ProposalError):
        proposal.generate_final_proposal(_candidate(), _deep_analysis(), {"technical_snapshot": _technical()})


def test_non_json_response_raises(monkeypatch):
    monkeypatch.setattr(proposal, "_call_claude", lambda prompt, **kw: "not json")
    with pytest.raises(proposal.ProposalError):
        proposal.generate_final_proposal(_candidate(), _deep_analysis(), {"technical_snapshot": _technical()})


def test_ai_call_failure_becomes_proposal_error(monkeypatch):
    def raise_error(prompt, **kw):
        raise proposal.AnalysisError("cli boom")
    monkeypatch.setattr(proposal, "_call_claude", raise_error)
    with pytest.raises(proposal.ProposalError):
        proposal.generate_final_proposal(_candidate(), _deep_analysis(), {"technical_snapshot": _technical()})
