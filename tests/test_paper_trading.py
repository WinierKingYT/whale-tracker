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
    assert position["position_size_usd"] == round(paper_trading.VIRTUAL_CAPITAL_USD * 0.01, 2)
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
