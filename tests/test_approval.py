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


def _pretend_ready(monkeypatch) -> None:
    # What "ready" requires is test_evaluation's job; here only the
    # ASAMA5_ENABLED x ready combination is under test.
    monkeypatch.setattr(approval, "evaluate_paper_trading", lambda storage: {"ready_for_asama5": True})


def _open_all_gates(monkeypatch, db, *, price: float = 70000.0) -> None:
    """Every approval_blockers gate satisfied: flag on, ready, capital set,
    fresh market snapshot at `price`, Risk Guard clear (empty DB)."""
    monkeypatch.setattr(approval, "ASAMA5_ENABLED", True)
    monkeypatch.setattr(approval, "ASAMA5_CAPITAL_USD", 500.0)
    _pretend_ready(monkeypatch)
    _seed_btc_price(db, price, minutes_ago=1)


def _candidate(db) -> int:
    return db.insert_signal_candidate({
        "symbol": "BTCUSDT", "direction": "accumulation", "confidence": 0.9,
        "components": {}, "rationale": [], "generated_at": _now(),
    })


def test_asama5_active_false_by_default_even_when_ready(tmp_path, monkeypatch):
    _pretend_ready(monkeypatch)
    with Storage(tmp_path / "t.db") as db:
        assert approval.asama5_active(db) is False  # ASAMA5_ENABLED is off by default


def test_asama5_active_true_only_when_both_gates_hold(tmp_path, monkeypatch):
    monkeypatch.setattr(approval, "ASAMA5_ENABLED", True)
    _pretend_ready(monkeypatch)
    with Storage(tmp_path / "t.db") as db:
        assert approval.asama5_active(db) is True


def test_asama5_stays_off_when_btc_hold_is_beaten_without_an_edge(tmp_path, monkeypatch):
    """The real-data failure mode this gate was tightened for: enough trades
    that beat BTC-hold, but no evidence entries beat random ones."""
    monkeypatch.setattr(approval, "ASAMA5_ENABLED", True)
    with Storage(tmp_path / "t.db") as db:
        _seed_ready_for_asama5(db)
        scorecard = evaluation.evaluate_paper_trading(db)
        assert scorecard["beats_btc_hold"] is True and scorecard["ready_for_asama5"] is False
        assert approval.asama5_active(db) is False


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
    with Storage(tmp_path / "t.db") as db:
        _open_all_gates(monkeypatch, db)
        candidate_id = db.insert_signal_candidate({
            "symbol": "BTCUSDT", "direction": "accumulation", "confidence": 0.9,
            "components": {}, "rationale": [], "generated_at": _now(),
        })
        request = approval.create_approval_request(
            db, candidate_id, _proposal(), 70000.0, _technical(), symbol="BTCUSDT",
        )

        assert request is not None
        assert request["status"] == "pending"
        # $5 risk (1% of 500) over a 68000/70000 stop (2.857%) = $175 notional
        assert request["position_size_usd"] == 175.0
        pending = db.pending_approval_requests()
        assert len(pending) == 1
        assert pending[0]["id"] == request["id"]


def test_create_approval_request_returns_none_for_broken_setup(tmp_path, monkeypatch):
    with Storage(tmp_path / "t.db") as db:
        _open_all_gates(monkeypatch, db)
        candidate_id = db.insert_signal_candidate({
            "symbol": "BTCUSDT", "direction": "accumulation", "confidence": 0.9,
            "components": {}, "rationale": [], "generated_at": _now(),
        })
        # market_price already past take_profit_price -> broken setup
        _seed_btc_price(db, 90000.0, minutes_ago=0)
        request = approval.create_approval_request(
            db, candidate_id, _proposal(), 90000.0, _technical(), symbol="BTCUSDT",
        )
        assert request is None
        assert db.pending_approval_requests() == []


def test_decide_approval_request_approve_removes_from_pending(tmp_path, monkeypatch):
    with Storage(tmp_path / "t.db") as db:
        _open_all_gates(monkeypatch, db)
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
    with Storage(tmp_path / "t.db") as db:
        _open_all_gates(monkeypatch, db)
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


# --- WT-05.1 P0: the gate lives inside create_approval_request itself ---

def _direct_call(db):
    return approval.create_approval_request(db, _candidate(db), _proposal(), 70000.0, _technical(), symbol="BTCUSDT")


def test_direct_call_is_refused_when_flag_is_off(tmp_path, monkeypatch):
    with Storage(tmp_path / "t.db") as db:
        _open_all_gates(monkeypatch, db)
        monkeypatch.setattr(approval, "ASAMA5_ENABLED", False)
        assert _direct_call(db) is None
        assert "ASAMA5_ENABLED kapalı" in approval.approval_blockers(db, "BTCUSDT", 70000.0)
        assert db.pending_approval_requests() == []


def test_direct_call_is_refused_when_not_ready(tmp_path, monkeypatch):
    with Storage(tmp_path / "t.db") as db:
        _open_all_gates(monkeypatch, db)
        monkeypatch.setattr(approval, "evaluate_paper_trading", lambda storage: {"ready_for_asama5": False})
        assert _direct_call(db) is None


def test_direct_call_is_refused_on_stale_evidence(tmp_path, monkeypatch):
    with Storage(tmp_path / "t.db") as db:
        _open_all_gates(monkeypatch, db)
        stale = datetime.now(UTC) + timedelta(hours=2)  # evaluate "now" two hours after the snapshot
        assert approval.create_approval_request(
            db, _candidate(db), _proposal(), 70000.0, _technical(), symbol="BTCUSDT", now=stale,
        ) is None
        assert any("bayat" in b for b in approval.approval_blockers(db, "BTCUSDT", 70000.0, now=stale))


def test_direct_call_is_refused_when_price_disagrees_with_snapshot(tmp_path, monkeypatch):
    with Storage(tmp_path / "t.db") as db:
        _open_all_gates(monkeypatch, db, price=73000.0)
        assert _direct_call(db) is None  # caller says 70000, fresh snapshot says 73000


def test_direct_call_is_refused_by_risk_guard(tmp_path, monkeypatch):
    with Storage(tmp_path / "t.db") as db:
        _open_all_gates(monkeypatch, db)
        monkeypatch.setattr(approval, "risk_guard_blocks_new_position", lambda storage, now=None: "tavan doldu")
        assert _direct_call(db) is None
        assert "Risk Guard: tavan doldu" in approval.approval_blockers(db, "BTCUSDT", 70000.0)


def test_all_gates_open_creates_request(tmp_path, monkeypatch):
    with Storage(tmp_path / "t.db") as db:
        _open_all_gates(monkeypatch, db)
        assert approval.approval_blockers(db, "BTCUSDT", 70000.0) == []
        assert _direct_call(db) is not None


# --- WT-05.1 P1: approval lifecycle ---

def _pending(db, monkeypatch, *, now=None):
    _open_all_gates(monkeypatch, db)
    request = approval.create_approval_request(db, _candidate(db), _proposal(), 70000.0, _technical(),
                                               symbol="BTCUSDT", now=now)
    assert request is not None
    return request


def test_request_has_expiry(tmp_path, monkeypatch):
    with Storage(tmp_path / "t.db") as db:
        request = _pending(db, monkeypatch)
        created = datetime.fromisoformat(request["created_at"])
        assert datetime.fromisoformat(request["expires_at"]) - created == approval.APPROVAL_TTL


def test_expired_request_cannot_be_approved(tmp_path, monkeypatch):
    with Storage(tmp_path / "t.db") as db:
        request = _pending(db, monkeypatch)
        later = datetime.now(UTC) + approval.APPROVAL_TTL + timedelta(minutes=1)
        _seed_btc_price(db, 70000.0, minutes_ago=-61)  # fresh at `later`
        status, reasons = approval.approve_request(db, request["id"], 70000.0, now=later)
        assert status in {"expired", "invalidated"} and "süresi doldu" in reasons
        assert db.get_approval_request(request["id"])["status"] != "approved"


def test_expire_stale_requests_sweeps_pending(tmp_path, monkeypatch):
    with Storage(tmp_path / "t.db") as db:
        request = _pending(db, monkeypatch)
        assert approval.expire_stale_requests(db) == []
        later = datetime.now(UTC) + approval.APPROVAL_TTL
        assert approval.expire_stale_requests(db, now=later) == [request["id"]]
        assert db.get_approval_request(request["id"])["status"] == "expired"


def test_price_drift_invalidates_at_approval(tmp_path, monkeypatch):
    """Proposed at $70,000, user approves at $73,000: old geometry no longer holds."""
    with Storage(tmp_path / "t.db") as db:
        request = _pending(db, monkeypatch)
        _seed_btc_price(db, 73000.0, minutes_ago=0)
        status, reasons = approval.approve_request(db, request["id"], 73000.0)
        assert status == "invalidated"
        assert any("fiyat kaydı" in r for r in reasons)
        assert db.get_approval_request(request["id"])["status"] == "invalidated"


def test_risk_guard_rechecked_at_approval(tmp_path, monkeypatch):
    with Storage(tmp_path / "t.db") as db:
        request = _pending(db, monkeypatch)
        monkeypatch.setattr(approval, "risk_guard_blocks_new_position", lambda storage, now=None: "günlük kayıp")
        status, reasons = approval.approve_request(db, request["id"], 70000.0)
        assert status == "invalidated" and "Risk Guard: günlük kayıp" in reasons


def test_stale_evidence_rechecked_at_approval(tmp_path, monkeypatch):
    with Storage(tmp_path / "t.db") as db:
        request = _pending(db, monkeypatch)
        soon = datetime.now(UTC) + timedelta(minutes=30)  # within TTL, but snapshot now 30 min old
        status, reasons = approval.approve_request(db, request["id"], 70000.0, now=soon)
        assert status == "invalidated" and any("bayat" in r for r in reasons)


def test_valid_request_is_approved_and_cannot_be_decided_twice(tmp_path, monkeypatch):
    with Storage(tmp_path / "t.db") as db:
        request = _pending(db, monkeypatch)
        assert approval.approve_request(db, request["id"], 70100.0) == ("approved", [])
        status, _ = approval.approve_request(db, request["id"], 70100.0)
        assert status == "approved"  # unchanged, not re-decided


def test_legacy_row_without_expiry_is_treated_as_expired(tmp_path, monkeypatch):
    with Storage(tmp_path / "t.db") as db:
        request = _pending(db, monkeypatch)
        db._conn.execute("UPDATE approval_requests SET expires_at = NULL WHERE id = ?", (request["id"],))
        assert approval.expire_stale_requests(db) == [request["id"]]
