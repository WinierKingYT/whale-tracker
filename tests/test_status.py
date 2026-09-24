from datetime import UTC, datetime

from whale_tracker import status as status_module
from whale_tracker.storage import Storage


def _now() -> str:
    return datetime.now(UTC).isoformat()


def test_compute_status_on_empty_db(tmp_path):
    with Storage(tmp_path / "t.db") as db:
        status = status_module.compute_status(db)

    assert status["market_snapshots"]["total"] == 0
    assert status["signal_candidates"]["total"] == 0
    assert status["paper_positions"]["open"] == 0
    assert status["paper_positions"]["closed"] == 0


def test_compute_status_counts_real_data(tmp_path):
    with Storage(tmp_path / "t.db") as db:
        db.insert_market_snapshot({
            "symbol": "BTCUSDT", "funding_rate": 0.0001, "open_interest": 100.0,
            "mark_price": 70000.0, "observed_at": _now(),
        })
        db.insert_market_snapshot({
            "symbol": "ETHUSDT", "funding_rate": 0.0002, "open_interest": 50.0,
            "mark_price": 3000.0, "observed_at": _now(),
        })
        candidate_id = db.insert_signal_candidate({
            "symbol": "BTCUSDT", "direction": "accumulation", "confidence": 0.9,
            "components": {}, "rationale": [], "generated_at": _now(),
        })
        db.insert_deep_analysis(candidate_id, {
            "assessment": "x", "counter_argument": "y", "risk_flags": [],
            "corroboration_strength": "strong",
        }, _now())
        db.insert_final_proposal(candidate_id, {
            "action": "long_candidate", "reason": None, "max_position_size_pct": 0.01,
            "stop_loss_price": 68000.0, "entry_rationale": "x", "worst_case_scenario": "y",
            "counter_arguments": [], "conviction": "high",
        }, _now())
        db.insert_paper_position({
            "signal_candidate_id": candidate_id, "symbol": "BTCUSDT", "entry_price": 70000.0,
            "stop_loss_price": 68000.0, "take_profit_price": 75000.0, "position_size_usd": 100.0,
            "status": "open", "opened_at": _now(),
        })

        status = status_module.compute_status(db)

    assert status["market_snapshots"]["total"] == 2
    assert status["market_snapshots"]["by_symbol"] == {"BTCUSDT": 1, "ETHUSDT": 1}
    assert status["market_snapshots"]["latest_prices"]["BTCUSDT"] == 70000.0
    assert status["signal_candidates"]["total"] == 1
    assert status["deep_analyses"]["by_strength"] == {"strong": 1}
    assert status["final_proposals"]["by_action"] == {"long_candidate": 1}
    assert status["paper_positions"]["open"] == 1
    assert status["paper_positions"]["closed"] == 0


def test_render_status_includes_db_path_and_key_numbers(tmp_path):
    db_path = tmp_path / "t.db"
    with Storage(db_path) as db:
        status = status_module.compute_status(db)
    report = status_module.render_status(status, db_path=db_path)
    assert str(db_path) in report
    assert "Sinyal adayı" in report
    assert "Kağıt pozisyon" in report


def test_render_status_shows_ai_call_quota_usage(tmp_path):
    db_path = tmp_path / "t.db"
    with Storage(db_path) as db:
        db.insert_ai_call_log(
            "kademe2_sonnet", attempted=4, succeeded=3, duration_ms=2000.0,
            error_reason="some failed", called_at=_now(),
        )
        status = status_module.compute_status(db)
    report = status_module.render_status(status, db_path=db_path)
    assert "AI çağrıları" in report
    assert "kademe2_sonnet" in report
    assert "3/4" in report


def test_render_status_omits_ai_section_when_no_calls_logged(tmp_path):
    db_path = tmp_path / "t.db"
    with Storage(db_path) as db:
        status = status_module.compute_status(db)
    report = status_module.render_status(status, db_path=db_path)
    assert "AI çağrıları" not in report
