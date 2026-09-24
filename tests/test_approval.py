from datetime import UTC, datetime, timedelta

from whale_tracker import approval, evaluation
from whale_tracker.storage import Storage


def _now(minutes_ago: float = 0) -> str:
    return (datetime.now(UTC) - timedelta(minutes=minutes_ago)).isoformat()


def _seed_btc_price(db, price: float, minutes_ago: float) -> None:
    db.insert_market_snapshot({
        "symbol": "BTCUSDT", "funding_rate": 0.0001, "open_interest": 1000.0,
        "mark_price": price, "observed_at": _now(minutes_ago),
    })


def _open_and_close(db, *, entry_price, exit_price, opened_minutes_ago, closed_minutes_ago):
    candidate_id = db.insert_signal_candidate({
        "symbol": "BTCUSDT", "direction": "accumulation", "confidence": 0.9, "components": {}, "rationale": [],
        "generated_at": _now(opened_minutes_ago),
    })
    position_id = db.insert_paper_position({
        "signal_candidate_id": candidate_id, "symbol": "BTCUSDT", "entry_price": entry_price,
        "stop_loss_price": entry_price * 0.95, "take_profit_price": entry_price * 1.05,
        "position_size_usd": 100.0, "status": "open", "opened_at": _now(opened_minutes_ago),
    })
    pnl_pct = (exit_price - entry_price) / entry_price
    pnl_usd = round(100.0 * pnl_pct, 2)
    db.close_paper_position(
        position_id, exit_price=exit_price, status="take_profit",
        closed_at=_now(closed_minutes_ago), pnl_usd=pnl_usd, pnl_pct=round(pnl_pct, 4),
    )


def _seed_ready_for_asama5(db) -> None:
    """Same shape as test_evaluation.py's own ready_for_asama5=True seed
    -- kept local rather than imported since each test file owns its
    fixtures in this codebase."""
    _seed_btc_price(db, 70000.0, minutes_ago=100)
    _seed_btc_price(db, 69000.0, minutes_ago=6)
    for _ in range(evaluation.MIN_POSITIONS_FOR_CONFIDENCE):
        _open_and_close(db, entry_price=70000.0, exit_price=73500.0, opened_minutes_ago=10, closed_minutes_ago=5)


def _proposal(**overrides):
    base = {"action": "long_candidate", "stop_loss_price": 68000.0, "max_position_size_pct": 0.01}
    base.update(overrides)
    return base


def _technical(**overrides):
    base = {"resistance": 72000.0}
    base.update(overrides)
    return base


def test_asama5_active_false_by_default_even_when_ready(tmp_path):
    with Storage(tmp_path / "t.db") as db:
        _seed_ready_for_asama5(db)
        assert evaluation.evaluate_paper_trading(db)["ready_for_asama5"] is True
        assert approval.asama5_active(db) is False  # ASAMA5_ENABLED is off by default


def test_asama5_active_true_only_when_both_gates_hold(tmp_path, monkeypatch):
    monkeypatch.setattr(approval, "ASAMA5_ENABLED", True)
    with Storage(tmp_path / "t.db") as db:
        _seed_ready_for_asama5(db)
        assert approval.asama5_active(db) is True


def test_asama5_active_false_when_enabled_but_not_yet_ready(tmp_path, monkeypatch):
    monkeypatch.setattr(approval, "ASAMA5_ENABLED", True)
    with Storage(tmp_path / "t.db") as db:
        assert approval.asama5_active(db) is False  # no closed positions yet


def test_create_approval_request_refuses_when_capital_unset(tmp_path):
    with Storage(tmp_path / "t.db") as db:
        candidate_id = db.insert_signal_candidate({
            "symbol": "BTCUSDT", "direction": "accumulation", "confidence": 0.9,
            "components": {}, "rationale": [], "generated_at": _now(),
        })
        request = approval.create_approval_request(
            db, candidate_id, _proposal(), 70000.0, _technical(), symbol="BTCUSDT",
        )
        assert request is None
        assert db.pending_approval_requests() == []


def test_create_approval_request_creates_pending_row(tmp_path, monkeypatch):
    monkeypatch.setattr(approval, "ASAMA5_CAPITAL_USD", 500.0)
    with Storage(tmp_path / "t.db") as db:
        candidate_id = db.insert_signal_candidate({
            "symbol": "BTCUSDT", "direction": "accumulation", "confidence": 0.9,
            "components": {}, "rationale": [], "generated_at": _now(),
        })
        request = approval.create_approval_request(
            db, candidate_id, _proposal(), 70000.0, _technical(), symbol="BTCUSDT",
        )

        assert request is not None
        assert request["status"] == "pending"
        assert request["position_size_usd"] == 5.0  # 500 * 0.01
        pending = db.pending_approval_requests()
        assert len(pending) == 1
        assert pending[0]["id"] == request["id"]


def test_create_approval_request_returns_none_for_broken_setup(tmp_path, monkeypatch):
    monkeypatch.setattr(approval, "ASAMA5_CAPITAL_USD", 500.0)
    with Storage(tmp_path / "t.db") as db:
        candidate_id = db.insert_signal_candidate({
            "symbol": "BTCUSDT", "direction": "accumulation", "confidence": 0.9,
            "components": {}, "rationale": [], "generated_at": _now(),
        })
        # market_price already past take_profit_price -> broken setup
        request = approval.create_approval_request(
            db, candidate_id, _proposal(), 90000.0, _technical(), symbol="BTCUSDT",
        )
        assert request is None
        assert db.pending_approval_requests() == []


def test_decide_approval_request_approve_removes_from_pending(tmp_path, monkeypatch):
    monkeypatch.setattr(approval, "ASAMA5_CAPITAL_USD", 500.0)
    with Storage(tmp_path / "t.db") as db:
        candidate_id = db.insert_signal_candidate({
            "symbol": "BTCUSDT", "direction": "accumulation", "confidence": 0.9,
            "components": {}, "rationale": [], "generated_at": _now(),
        })
        request = approval.create_approval_request(
            db, candidate_id, _proposal(), 70000.0, _technical(), symbol="BTCUSDT",
        )

        db.decide_approval_request(request["id"], status="approved", decided_at=_now(), note="test onayı")

        assert db.pending_approval_requests() == []
        stored = db.get_approval_request(request["id"])
        assert stored["status"] == "approved"
        assert stored["note"] == "test onayı"


def test_decide_approval_request_reject_removes_from_pending(tmp_path, monkeypatch):
    monkeypatch.setattr(approval, "ASAMA5_CAPITAL_USD", 500.0)
    with Storage(tmp_path / "t.db") as db:
        candidate_id = db.insert_signal_candidate({
            "symbol": "BTCUSDT", "direction": "accumulation", "confidence": 0.9,
            "components": {}, "rationale": [], "generated_at": _now(),
        })
        request = approval.create_approval_request(
            db, candidate_id, _proposal(), 70000.0, _technical(), symbol="BTCUSDT",
        )

        db.decide_approval_request(request["id"], status="rejected", decided_at=_now())

        assert db.pending_approval_requests() == []
        assert db.get_approval_request(request["id"])["status"] == "rejected"
