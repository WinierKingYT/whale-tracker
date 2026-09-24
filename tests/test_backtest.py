"""Offline tests for the historical backtest -- no network. The central
property under test is no-lookahead: at replay time `now`, nothing that
happened after `now` may be visible."""

from datetime import UTC, datetime, timedelta

import pytest

from whale_tracker.backtest import baseline, history
from whale_tracker.backtest.replay import (
    HistoricalDataGap,
    HistoricalMarketReplay,
    HistoricalOnchainReplay,
    HistoricalSentimentReplay,
    NoNewsReplay,
)
from whale_tracker.simulate import run_cycle
from whale_tracker.storage import Storage

DAY = datetime(2026, 9, 1, tzinfo=UTC)


def _ms(moment: datetime) -> int:
    return int(moment.timestamp() * 1000)


def _kline(open_time: datetime, minutes: int, o: float, h: float, l: float, c: float) -> list:
    close_time = _ms(open_time + timedelta(minutes=minutes)) - 1
    return [_ms(open_time), str(o), str(h), str(l), str(c), "0", close_time, "0", 0, "0", "0", "0"]


def _daily_history(days: int = 31) -> list:
    rows = [_kline(DAY - timedelta(days=i), 1440, 100, 105, 95, 100) for i in range(days, 0, -1)]
    # Lookahead trap: today's FINISHED daily candle, with a high nobody
    # could have known at 00:15 that day.
    rows.append(_kline(DAY, 1440, 100, 999_999, 95, 100))
    return rows


def _intraday_15m() -> list:
    rows = [_kline(DAY - timedelta(minutes=15 * i), 15, 100, 101, 99, 100) for i in range(96, 0, -1)]
    rows.append(_kline(DAY, 15, 100, 102, 98, 101))
    # Lookahead trap: a spike later the same day.
    rows.append(_kline(DAY + timedelta(minutes=15), 15, 101, 50_000, 101, 50_000))
    return rows


def _market(**overrides) -> HistoricalMarketReplay:
    kwargs = {
        "klines_15m": _intraday_15m(),
        "daily_klines": _daily_history(),
        "funding_history": [
            {"funding_time_ms": _ms(DAY - timedelta(hours=8)), "rate": 0.0001},
            {"funding_time_ms": _ms(DAY + timedelta(hours=8)), "rate": 0.009},  # future
        ],
        "start": DAY,
    }
    kwargs.update(overrides)
    return HistoricalMarketReplay("BTCUSDT", **kwargs)


def test_market_snapshot_uses_last_closed_15m_candle_only():
    market = _market()
    market.tick(minutes=15)  # now = 00:15, only the 00:00 candle has closed
    snapshot = market.market_snapshot()
    assert snapshot["mark_price"] == 101.0
    assert snapshot["observed_at"] == (DAY + timedelta(minutes=15)).isoformat()


def test_funding_is_last_settled_rate_not_a_future_one():
    market = _market()
    market.tick(minutes=15)
    assert market.market_snapshot()["funding_rate"] == 0.0001


def test_technical_snapshot_never_sees_todays_finished_candle_or_later_spike():
    market = _market()
    market.tick(minutes=15)
    technical = market.technical_snapshot()
    assert technical["resistance"] == 105.0  # not 999_999 (finished daily) or 50_000 (later spike)
    assert technical["current_price"] == 101.0


def test_market_snapshot_raises_on_data_gap_instead_of_guessing():
    market = _market(klines_15m=[], start=DAY)
    market.tick(minutes=15)
    with pytest.raises(HistoricalDataGap):
        market.market_snapshot()


def _event(minutes_after_day: int, *, amount: float = 5_000_000.0, to_exchange: str | None = "binance") -> dict:
    ts = int((DAY + timedelta(minutes=minutes_after_day)).timestamp())
    return {
        "tx_hash": f"0x{minutes_after_day:064x}", "log_index": 0, "block_number": 1_000 + minutes_after_day,
        "block_timestamp": ts, "token": "USDT", "from_address": "0x" + "1" * 40, "to_address": "0x" + "2" * 40,
        "amount_usd_estimate": amount, "raw_amount": str(int(amount * 1e6)),
        "from_known_exchange": None, "to_known_exchange": to_exchange,
    }


def test_onchain_replay_emits_each_event_once_at_its_block_time():
    replay = HistoricalOnchainReplay([_event(5), _event(20), _event(-60)])
    first = replay.tick_events(observed_at=(DAY + timedelta(minutes=15)).isoformat())
    assert [e["block_number"] for e in first] == [940, 1005]  # warm-up event + 00:05, not 00:20
    assert first[1]["observed_at"] == (DAY + timedelta(minutes=5)).isoformat()
    assert "block_timestamp" not in first[0]
    second = replay.tick_events(observed_at=(DAY + timedelta(minutes=30)).isoformat())
    assert [e["block_number"] for e in second] == [1020]


def test_sentiment_replay_picks_latest_published_value():
    entries = [
        {"timestamp": int((DAY - timedelta(days=1)).timestamp()), "value": 30.0, "label": "Fear"},
        {"timestamp": int(DAY.timestamp()), "value": 70.0, "label": "Greed"},
    ]
    replay = HistoricalSentimentReplay(entries)
    assert replay.tick(observed_at=(DAY - timedelta(hours=1)).isoformat())["value"] == 30.0
    assert replay.tick(observed_at=(DAY + timedelta(hours=1)).isoformat())["value"] == 70.0
    with pytest.raises(HistoricalDataGap):
        replay.tick(observed_at=(DAY - timedelta(days=5)).isoformat())


def test_events_from_logs_filters_by_amount_and_labels_both_sides():
    exchange = "0x" + "a" * 40
    logs = [
        {"data": hex(2_000_000 * 10**6), "topics": ["t", "0x" + "0" * 24 + exchange[2:], "0x" + "0" * 24 + "b" * 40],
         "transactionHash": "0x1", "logIndex": "0x0", "blockNumber": "0x10", "blockTimestamp": "0x64"},
        {"data": hex(10 * 10**6), "topics": ["t", "0x" + "0" * 24 + exchange[2:], "0x" + "0" * 24 + "b" * 40],
         "transactionHash": "0x2", "logIndex": "0x0", "blockNumber": "0x11", "blockTimestamp": "0x65"},
    ]
    events = history._events_from_logs(logs, 6, "USDT", min_usd=1_000_000, labels={exchange: "binance"})
    assert len(events) == 1
    assert events[0]["from_known_exchange"] == "binance"
    assert events[0]["to_known_exchange"] is None
    assert events[0]["block_timestamp"] == 100


def _history_row(minutes: int, price: float, *, support: float = 95.0, resistance: float = 110.0) -> dict:
    moment = DAY + timedelta(minutes=minutes)
    return {"observed_at": moment.isoformat(), "moment": moment, "mark_price": price,
            "support": support, "resistance": resistance}


def test_simulated_entry_follows_strategy_exit_rules():
    # stop = 95 * 0.98 = 93.1, target = 110 * 0.995 = 109.45
    winner = [_history_row(0, 100), _history_row(15, 105), _history_row(30, 110)]
    assert baseline._simulate_entry(winner, 0) == pytest.approx((109.45 - 100) / 100)

    loser = [_history_row(0, 100), _history_row(15, 90)]
    assert baseline._simulate_entry(loser, 0) == pytest.approx((93.1 - 100) / 100)

    never_closes = [_history_row(0, 100), _history_row(15, 101)]
    assert baseline._simulate_entry(never_closes, 0) is None

    broken_setup = [_history_row(0, 120), _history_row(15, 121)]  # already above target
    assert baseline._simulate_entry(broken_setup, 0) is None


def test_replay_classes_drive_the_real_pipeline_end_to_end(tmp_path):
    """Interface check: simulate.run_cycle must run unchanged on replays."""
    markets = {"BTCUSDT": _market()}
    onchain = HistoricalOnchainReplay([_event(-30, to_exchange=None) | {"from_known_exchange": "binance"}])
    sentiment = HistoricalSentimentReplay([{"timestamp": int(DAY.timestamp()), "value": 30.0, "label": "Fear"}])
    with Storage(tmp_path / "bt.db") as db:
        result = run_cycle(db, markets, onchain, sentiment, NoNewsReplay(), with_ai=False)
        assert db.latest_market_snapshot("BTCUSDT")["mark_price"] == 101.0
        assert [c["direction"] for c in result["candidates"]] == ["accumulation"]  # net outflow from an exchange
