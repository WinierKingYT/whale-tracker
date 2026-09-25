from datetime import UTC, datetime, timedelta

from whale_tracker import paper_trading
from whale_tracker.storage import Storage


def _proposal(**overrides):
    base = {"action": "long_candidate", "stop_loss_price": 68600.0, "max_position_size_pct": 0.01}
    base.update(overrides)
    return base


def _technical(resistance=75000.0):
    return {"resistance": resistance}


def test_open_position_computes_take_profit_and_size():
    position = paper_trading.open_position(1, _proposal(), market_price=70000.0, technical=_technical())
    assert position is not None
    assert position["symbol"] == "BTCUSDT"  # default when no symbol is passed
    assert position["entry_price"] == 70000.0
    assert position["stop_loss_price"] == 68600.0
    assert position["take_profit_price"] == round(75000.0 * (1 - paper_trading.TAKE_PROFIT_RESISTANCE_BUFFER_PCT), 2)
    # 1% ACCOUNT risk over a 2% stop: $100 risk / 0.02 = $5,000 notional,
    # so hitting the stop loses exactly 1% of capital.
    assert position["position_size_usd"] == 5000.0
    loss_at_stop = position["position_size_usd"] * (70000.0 - 68600.0) / 70000.0
    assert loss_at_stop == paper_trading.VIRTUAL_CAPITAL_USD * 0.01
    assert position["status"] == "open"


def test_open_position_carries_the_given_symbol():
    position = paper_trading.open_position(
        1, _proposal(stop_loss_price=2940.0), market_price=3000.0, technical=_technical(resistance=3300.0),
        symbol="ETHUSDT",
    )
    assert position["symbol"] == "ETHUSDT"


def test_open_position_returns_none_for_no_action_proposal():
    assert paper_trading.open_position(1, _proposal(action="no_action"), 70000.0, _technical()) is None


def test_open_position_returns_none_without_technical_snapshot():
    assert paper_trading.open_position(1, _proposal(), 70000.0, None) is None


def test_open_position_returns_none_when_price_already_past_take_profit():
    # market price already at/above the resistance-derived take-profit -- broken setup
    assert paper_trading.open_position(1, _proposal(), market_price=75000.0, technical=_technical(resistance=75000.0)) is None


def test_open_position_returns_none_when_price_already_through_stop_loss():
    assert paper_trading.open_position(1, _proposal(stop_loss_price=71000.0), market_price=70000.0, technical=_technical()) is None


def test_check_and_close_positions_closes_on_stop_loss(tmp_path):
    with Storage(tmp_path / "t.db") as db:
        candidate_id = db.insert_signal_candidate({
            "direction": "accumulation", "confidence": 0.9, "components": {}, "rationale": [],
            "generated_at": datetime.now(UTC).isoformat(),
        })
        db.insert_paper_position({
            "signal_candidate_id": candidate_id, "entry_price": 70000.0, "stop_loss_price": 68600.0,
            "take_profit_price": 74625.0, "position_size_usd": 100.0, "status": "open",
            "opened_at": datetime.now(UTC).isoformat(),
        })

        closed = paper_trading.check_and_close_positions(db, current_prices={"BTCUSDT": 68500.0})
        remaining_open = db.open_paper_positions()

    assert len(closed) == 1
    assert closed[0]["status"] == "stopped_out"
    assert closed[0]["exit_price"] == 68600.0
    assert closed[0]["pnl_usd"] < 0
    assert remaining_open == []


def test_check_and_close_positions_closes_on_take_profit(tmp_path):
    with Storage(tmp_path / "t.db") as db:
        candidate_id = db.insert_signal_candidate({
            "direction": "accumulation", "confidence": 0.9, "components": {}, "rationale": [],
            "generated_at": datetime.now(UTC).isoformat(),
        })
        db.insert_paper_position({
            "signal_candidate_id": candidate_id, "entry_price": 70000.0, "stop_loss_price": 68600.0,
            "take_profit_price": 74625.0, "position_size_usd": 100.0, "status": "open",
            "opened_at": datetime.now(UTC).isoformat(),
        })

        closed = paper_trading.check_and_close_positions(db, current_prices={"BTCUSDT": 75000.0})

    assert closed[0]["status"] == "take_profit"
    assert closed[0]["pnl_usd"] > 0


def test_check_and_close_positions_expires_after_max_hold_days(tmp_path):
    with Storage(tmp_path / "t.db") as db:
        candidate_id = db.insert_signal_candidate({
            "direction": "accumulation", "confidence": 0.9, "components": {}, "rationale": [],
            "generated_at": datetime.now(UTC).isoformat(),
        })
        stale_open = (datetime.now(UTC) - timedelta(days=paper_trading.MAX_HOLD_DAYS + 1)).isoformat()
        db.insert_paper_position({
            "signal_candidate_id": candidate_id, "entry_price": 70000.0, "stop_loss_price": 68600.0,
            "take_profit_price": 74625.0, "position_size_usd": 100.0, "status": "open",
            "opened_at": stale_open,
        })

        closed = paper_trading.check_and_close_positions(db, current_prices={"BTCUSDT": 71000.0})

    assert closed[0]["status"] == "expired"
    assert closed[0]["exit_price"] == 71000.0


def test_check_and_close_positions_matches_each_position_to_its_own_symbol_price(tmp_path):
    with Storage(tmp_path / "t.db") as db:
        btc_candidate = db.insert_signal_candidate({
            "symbol": "BTCUSDT", "direction": "accumulation", "confidence": 0.9,
            "components": {}, "rationale": [], "generated_at": datetime.now(UTC).isoformat(),
        })
        eth_candidate = db.insert_signal_candidate({
            "symbol": "ETHUSDT", "direction": "accumulation", "confidence": 0.9,
            "components": {}, "rationale": [], "generated_at": datetime.now(UTC).isoformat(),
        })
        db.insert_paper_position({
            "signal_candidate_id": btc_candidate, "symbol": "BTCUSDT", "entry_price": 70000.0,
            "stop_loss_price": 68600.0, "take_profit_price": 74625.0, "position_size_usd": 100.0,
            "status": "open", "opened_at": datetime.now(UTC).isoformat(),
        })
        db.insert_paper_position({
            "signal_candidate_id": eth_candidate, "symbol": "ETHUSDT", "entry_price": 3000.0,
            "stop_loss_price": 2940.0, "take_profit_price": 3200.0, "position_size_usd": 100.0,
            "status": "open", "opened_at": datetime.now(UTC).isoformat(),
        })

        # BTC price stays flat (no close); ETH price hits its own take-profit.
        # A BTC price this far below ETH's take-profit must not accidentally
        # trigger the BTC position -- each position checks only its own symbol.
        closed = paper_trading.check_and_close_positions(db, current_prices={"BTCUSDT": 71000.0, "ETHUSDT": 3200.0})

    assert len(closed) == 1
    assert closed[0]["symbol"] == "ETHUSDT"
    assert closed[0]["status"] == "take_profit"


def test_check_and_close_positions_skips_position_whose_symbol_has_no_price_this_cycle(tmp_path):
    with Storage(tmp_path / "t.db") as db:
        candidate_id = db.insert_signal_candidate({
            "symbol": "ETHUSDT", "direction": "accumulation", "confidence": 0.9,
            "components": {}, "rationale": [], "generated_at": datetime.now(UTC).isoformat(),
        })
        db.insert_paper_position({
            "signal_candidate_id": candidate_id, "symbol": "ETHUSDT", "entry_price": 3000.0,
            "stop_loss_price": 2940.0, "take_profit_price": 3200.0, "position_size_usd": 100.0,
            "status": "open", "opened_at": datetime.now(UTC).isoformat(),
        })

        # only BTCUSDT price available this cycle (e.g. ETH fetch failed) --
        # the ETH position must be left open, not crash and not close.
        closed = paper_trading.check_and_close_positions(db, current_prices={"BTCUSDT": 71000.0})
        remaining_open = db.open_paper_positions()

    assert closed == []
    assert len(remaining_open) == 1


def test_check_and_close_positions_leaves_open_position_untouched(tmp_path):
    with Storage(tmp_path / "t.db") as db:
        candidate_id = db.insert_signal_candidate({
            "direction": "accumulation", "confidence": 0.9, "components": {}, "rationale": [],
            "generated_at": datetime.now(UTC).isoformat(),
        })
        db.insert_paper_position({
            "signal_candidate_id": candidate_id, "entry_price": 70000.0, "stop_loss_price": 68600.0,
            "take_profit_price": 74625.0, "position_size_usd": 100.0, "status": "open",
            "opened_at": datetime.now(UTC).isoformat(),
        })

        closed = paper_trading.check_and_close_positions(db, current_prices={"BTCUSDT": 71000.0})
        remaining_open = db.open_paper_positions()

    assert closed == []
    assert len(remaining_open) == 1


def _candidate(db, symbol="BTCUSDT"):
    return db.insert_signal_candidate({
        "symbol": symbol, "direction": "accumulation", "confidence": 0.9,
        "components": {}, "rationale": [], "generated_at": datetime.now(UTC).isoformat(),
    })


def _open_position_row(db, *, entry_price=70000.0, size_usd=100.0, symbol="BTCUSDT"):
    return db.insert_paper_position({
        "signal_candidate_id": _candidate(db, symbol), "symbol": symbol, "entry_price": entry_price,
        "stop_loss_price": entry_price * 0.95, "take_profit_price": entry_price * 1.05,
        "position_size_usd": size_usd, "status": "open", "opened_at": datetime.now(UTC).isoformat(),
    })


def _closed_position_today(db, *, pnl_usd, symbol="BTCUSDT"):
    position_id = _open_position_row(db, symbol=symbol)
    db.close_paper_position(
        position_id, exit_price=70000.0, status="stopped_out",
        closed_at=datetime.now(UTC).isoformat(), pnl_usd=pnl_usd, pnl_pct=0.0,
    )


def test_risk_guard_allows_new_position_by_default(tmp_path):
    with Storage(tmp_path / "t.db") as db:
        assert paper_trading.risk_guard_blocks_new_position(db) is None


def test_risk_guard_blocks_when_concurrent_cap_reached(tmp_path):
    with Storage(tmp_path / "t.db") as db:
        for _ in range(paper_trading.MAX_CONCURRENT_POSITIONS):
            _open_position_row(db)
        reason = paper_trading.risk_guard_blocks_new_position(db)
    assert reason is not None
    assert "pozisyon tavanı" in reason


def test_risk_guard_allows_when_below_concurrent_cap(tmp_path):
    with Storage(tmp_path / "t.db") as db:
        for _ in range(paper_trading.MAX_CONCURRENT_POSITIONS - 1):
            _open_position_row(db)
        reason = paper_trading.risk_guard_blocks_new_position(db)
    assert reason is None


def test_risk_guard_blocks_when_daily_loss_limit_exceeded(tmp_path):
    with Storage(tmp_path / "t.db") as db:
        # -3.5% of VIRTUAL_CAPITAL_USD in one day, past the 3% limit
        _closed_position_today(db, pnl_usd=-paper_trading.VIRTUAL_CAPITAL_USD * 0.035)
        reason = paper_trading.risk_guard_blocks_new_position(db)
    assert reason is not None
    assert "günlük kayıp" in reason


def test_risk_guard_allows_when_daily_loss_within_limit(tmp_path):
    with Storage(tmp_path / "t.db") as db:
        _closed_position_today(db, pnl_usd=-paper_trading.VIRTUAL_CAPITAL_USD * 0.01)
        reason = paper_trading.risk_guard_blocks_new_position(db)
    assert reason is None


def test_risk_guard_daily_loss_only_counts_today_not_earlier_losses(tmp_path):
    with Storage(tmp_path / "t.db") as db:
        candidate_id = _candidate(db)
        position_id = db.insert_paper_position({
            "signal_candidate_id": candidate_id, "symbol": "BTCUSDT", "entry_price": 70000.0,
            "stop_loss_price": 66500.0, "take_profit_price": 73500.0, "position_size_usd": 100.0,
            "status": "open", "opened_at": (datetime.now(UTC) - timedelta(days=2)).isoformat(),
        })
        # a big loss, but closed two days ago -- must not count against today
        db.close_paper_position(
            position_id, exit_price=66500.0, status="stopped_out",
            closed_at=(datetime.now(UTC) - timedelta(days=2)).isoformat(),
            pnl_usd=-paper_trading.VIRTUAL_CAPITAL_USD * 0.10, pnl_pct=-0.05,
        )
        reason = paper_trading.risk_guard_blocks_new_position(db)
    assert reason is None


def test_daily_pnl_pct_sums_only_todays_closed_positions(tmp_path):
    with Storage(tmp_path / "t.db") as db:
        _closed_position_today(db, pnl_usd=30.0)
        _closed_position_today(db, pnl_usd=-10.0)
        pct = paper_trading._daily_pnl_pct(db, now=datetime.now(UTC))
    assert abs(pct - 20.0 / paper_trading.VIRTUAL_CAPITAL_USD) < 1e-9
