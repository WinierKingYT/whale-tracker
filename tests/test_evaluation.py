from datetime import UTC, datetime, timedelta

from whale_tracker import evaluation
from whale_tracker.paper_trading import VIRTUAL_CAPITAL_USD
from whale_tracker.storage import Storage


def _now(minutes_ago: float = 0) -> str:
    return (datetime.now(UTC) - timedelta(minutes=minutes_ago)).isoformat()


def _open_and_close(db, *, entry_price, exit_price, status, opened_minutes_ago, closed_minutes_ago, size_usd=100.0):
    candidate_id = db.insert_signal_candidate({
        "direction": "accumulation", "confidence": 0.9, "components": {}, "rationale": [],
        "generated_at": _now(opened_minutes_ago),
    })
    position_id = db.insert_paper_position({
        "signal_candidate_id": candidate_id, "entry_price": entry_price,
        "stop_loss_price": entry_price * 0.95, "take_profit_price": entry_price * 1.05,
        "position_size_usd": size_usd, "status": "open", "opened_at": _now(opened_minutes_ago),
    })
    pnl_pct = (exit_price - entry_price) / entry_price
    pnl_usd = round(size_usd * pnl_pct, 2)
    db.close_paper_position(
        position_id, exit_price=exit_price, status=status,
        closed_at=_now(closed_minutes_ago), pnl_usd=pnl_usd, pnl_pct=round(pnl_pct, 4),
    )
    return position_id


def test_no_closed_positions_is_insufficient_data(tmp_path):
    with Storage(tmp_path / "t.db") as db:
        scorecard = evaluation.evaluate_paper_trading(db)
    assert scorecard["insufficient_data"] is True
    assert scorecard["closed_position_count"] == 0


def test_open_position_alone_does_not_count_as_closed(tmp_path):
    with Storage(tmp_path / "t.db") as db:
        candidate_id = db.insert_signal_candidate({
            "direction": "accumulation", "confidence": 0.9, "components": {}, "rationale": [],
            "generated_at": _now(),
        })
        db.insert_paper_position({
            "signal_candidate_id": candidate_id, "entry_price": 70000.0, "stop_loss_price": 68600.0,
            "take_profit_price": 74625.0, "position_size_usd": 100.0, "status": "open", "opened_at": _now(),
        })
        scorecard = evaluation.evaluate_paper_trading(db)
    assert scorecard["closed_position_count"] == 0
    assert scorecard["open_position_count"] == 1
    assert scorecard["insufficient_data"] is True


def test_win_rate_and_pnl_with_mixed_outcomes(tmp_path):
    with Storage(tmp_path / "t.db") as db:
        # a win: +5%
        _open_and_close(db, entry_price=70000.0, exit_price=73500.0, status="take_profit",
                         opened_minutes_ago=100, closed_minutes_ago=90)
        # a loss: -2%
        _open_and_close(db, entry_price=71000.0, exit_price=69580.0, status="stopped_out",
                         opened_minutes_ago=80, closed_minutes_ago=70)

        scorecard = evaluation.evaluate_paper_trading(db)

    assert scorecard["closed_position_count"] == 2
    assert scorecard["win_rate"] == 0.5
    assert scorecard["avg_win_pct"] == 0.05
    assert scorecard["avg_loss_pct"] == -0.02
    assert scorecard["win_loss_ratio"] == 2.5  # 5% win / 2% loss
    assert scorecard["total_pnl_usd"] == 3.0  # +5 - 2
    assert scorecard["strategy_return_pct"] == round(3.0 / VIRTUAL_CAPITAL_USD, 4)


def test_max_drawdown_tracks_worst_peak_to_trough(tmp_path):
    with Storage(tmp_path / "t.db") as db:
        # equity: 10000 -> +2 (win, +2%*$100) -> -200 (loss, -10%*$2000) -> +150 (partial recover, +7.5%*$2000)
        _open_and_close(db, entry_price=70000.0, exit_price=71400.0, status="take_profit",
                         opened_minutes_ago=100, closed_minutes_ago=90, size_usd=100.0)
        _open_and_close(db, entry_price=70000.0, exit_price=63000.0, status="stopped_out",
                         opened_minutes_ago=80, closed_minutes_ago=70, size_usd=2000.0)
        _open_and_close(db, entry_price=70000.0, exit_price=75250.0, status="take_profit",
                         opened_minutes_ago=60, closed_minutes_ago=50, size_usd=2000.0)

        scorecard = evaluation.evaluate_paper_trading(db)

    # peak after trade 1: 10002. trough after trade 2 (-200 usd): 9802. dd = 200/10002
    assert scorecard["max_drawdown_pct"] == round(200 / 10002, 4)


def test_btc_hold_comparison_uses_first_entry_and_last_exit_price(tmp_path):
    with Storage(tmp_path / "t.db") as db:
        _open_and_close(db, entry_price=70000.0, exit_price=77000.0, status="take_profit",
                         opened_minutes_ago=100, closed_minutes_ago=50)

        scorecard = evaluation.evaluate_paper_trading(db)

    # entry 70000 -> exit 77000 is +10% for both the single trade and BTC-hold here
    assert scorecard["btc_hold_return_pct"] == 0.1
    assert scorecard["beats_btc_hold"] is False  # strategy return < btc hold return (position was only ~1% of capital)


def test_below_confidence_floor_still_reports_but_flags_insufficient(tmp_path):
    with Storage(tmp_path / "t.db") as db:
        _open_and_close(db, entry_price=70000.0, exit_price=71000.0, status="take_profit",
                         opened_minutes_ago=10, closed_minutes_ago=5)
        scorecard = evaluation.evaluate_paper_trading(db)

    assert scorecard["closed_position_count"] == 1
    assert scorecard["insufficient_data"] is True
    assert scorecard["win_rate"] == 1.0


def test_render_report_handles_zero_closed_positions():
    scorecard = {"closed_position_count": 0, "open_position_count": 2, "insufficient_data": True}
    report = evaluation.render_evaluation_report(scorecard)
    assert "Henüz kapanmış" in report
    assert "açık: 2" in report


def test_render_report_shows_full_scorecard(tmp_path):
    with Storage(tmp_path / "t.db") as db:
        for _ in range(evaluation.MIN_POSITIONS_FOR_CONFIDENCE):
            _open_and_close(db, entry_price=70000.0, exit_price=71000.0, status="take_profit",
                             opened_minutes_ago=10, closed_minutes_ago=5)
        scorecard = evaluation.evaluate_paper_trading(db)

    report = evaluation.render_evaluation_report(scorecard)
    assert "İsabet oranı" in report
    assert "BTC-hold" in report
    assert "UYARI" not in report  # enough positions, no low-confidence warning
