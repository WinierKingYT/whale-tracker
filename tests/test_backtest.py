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


def test_events_from_asset_transfers_parses_alchemy_shape_and_filters():
    exchange = "0x" + "a" * 40
    usdt = "0xdac17f958d2ee523a2206206994597c13d831ec7"
    transfer = {
        "blockNum": "0x10", "uniqueId": "0xabc:log:496", "hash": "0xabc", "from": exchange, "to": "0x" + "b" * 40,
        "rawContract": {"value": hex(3_000_000 * 10**6), "address": usdt, "decimal": "0x6"},
        "metadata": {"blockTimestamp": "2026-09-24T05:07:23.000Z"},
    }
    small = {**transfer, "uniqueId": "0xdef:log:1", "hash": "0xdef",
             "rawContract": {**transfer["rawContract"], "value": hex(5 * 10**6)}}
    events = history._events_from_asset_transfers([transfer, small], min_usd=1_000_000, labels={exchange: "okx"})
    assert len(events) == 1
    assert events[0]["log_index"] == 496
    assert events[0]["token"] == "USDT"
    assert events[0]["from_known_exchange"] == "okx"
    assert events[0]["block_timestamp"] == int(datetime(2026, 9, 24, 5, 7, 23, tzinfo=UTC).timestamp())


def test_rpc_errors_never_leak_the_url(monkeypatch):
    """Keyed providers put the API key in the URL path; a real failure
    printed it into session output once before this was fixed."""
    from whale_tracker.sources import onchain

    class _BadResponse:
        ok = False
        status_code = 400
        text = '{"error":"range too large"}'

    monkeypatch.setattr(onchain.requests, "post", lambda *a, **k: _BadResponse())
    monkeypatch.setattr(onchain.time, "sleep", lambda *_: None)
    with pytest.raises(onchain.OnchainScanError) as caught:
        onchain._rpc("eth_getLogs", [], retries=2, url="https://rpc.example/v2/SECRET_KEY_123")
    assert "SECRET_KEY_123" not in str(caught.value)
    assert "range too large" in str(caught.value)
    assert caught.value.__cause__ is None


class _HistoryStorage:
    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows

    def price_and_levels_history(self, symbol: str) -> list[dict]:
        return self._rows


def _sawtooth(cycles: int) -> list[dict]:
    # Period-4 pattern 100, 110, 100, 90: an entry at a "100 then 110"
    # moment wins, "100 then 90" loses, and 110/90 moments are invalid
    # setups (past target / below stop).
    prices = [100.0, 110.0, 100.0, 90.0]
    return [
        {"observed_at": (DAY + timedelta(minutes=15 * i)).isoformat(), "mark_price": prices[i % 4],
         "support": 95.0, "resistance": 110.0}
        for i in range(cycles)
    ]


def test_circular_shift_baseline_preserves_entry_spacing():
    rows = _sawtooth(800)
    winners = [rows[i] for i in range(0, 400, 40)]  # all at i % 4 == 0
    positions = [{"symbol": "BTCUSDT", "opened_at": r["observed_at"], "pnl_pct": (109.45 - 100) / 100} for r in winners]
    result = baseline.random_entry_baseline(_HistoryStorage(rows), positions, trials=400, seed=1)
    assert result["method"] == "circular_shift"
    # One shared shift moves every entry into the same phase, so each
    # valid trial is all-wins or all-losses -- never a mix. Independent
    # draws would instead average to a tight band in between.
    assert result["random_stdev_of_means"] > 0.07
    assert 0.3 < result["p_value"] < 0.7


def test_baseline_returns_none_when_period_too_short_to_shift():
    rows = _sawtooth(150)
    positions = [{"symbol": "BTCUSDT", "opened_at": rows[0]["observed_at"], "pnl_pct": 0.01}]
    assert baseline.random_entry_baseline(_HistoryStorage(rows), positions) is None


def test_rolling_net_inflow_matches_signal_py_window(tmp_path):
    from whale_tracker import signal
    from whale_tracker.backtest.signal_ic import rolling_net_inflow

    events = [
        _event(-30 * 60) | {"observed_at": (DAY - timedelta(hours=30)).isoformat()},  # outside 24h at t
        _event(0) | {"tx_hash": "0xa", "observed_at": (DAY - timedelta(hours=2)).isoformat()},
        _event(0, to_exchange="DEX: Uniswap") | {"tx_hash": "0xb", "observed_at": (DAY - timedelta(hours=1)).isoformat()},
        _event(0, to_exchange=None) | {"tx_hash": "0xc", "from_known_exchange": "okx", "amount_usd_estimate": 2e6,
                                       "observed_at": (DAY - timedelta(hours=1)).isoformat()},
    ]
    with Storage(tmp_path / "f.db") as db:
        for e in events:
            db.insert_onchain_event({k: v for k, v in e.items() if k != "block_timestamp"})
        expected = signal._aggregate_exchange_flow(db, hours=24, now=DAY)["net_inflow_usd"]
    assert rolling_net_inflow(events, [DAY]) == [expected] == [5_000_000.0 - 2_000_000.0]


class _IcStorage:
    def __init__(self, rows, events):
        self._rows, self._events = rows, events

    def price_and_levels_history(self, symbol):
        return self._rows

    def recent_onchain_events(self, limit=50):
        return self._events


def test_information_coefficient_finds_a_signal_that_drives_returns():
    import random as _random
    from whale_tracker.backtest.signal_ic import information_coefficient

    rng = _random.Random(4)
    rows, events, price = [], [], 100.0
    for block in range(20):  # 20 blocks of 3 days, each with a persistent direction
        direction = rng.choice((1, -1))
        for i in range(288):
            moment = DAY + timedelta(minutes=15 * (block * 288 + i))
            if i % 48 == 0:  # an exchange flow every 12h in the block's direction
                tag = {"from_known_exchange": "binance", "to_known_exchange": None} if direction > 0 else {}
                events.append(_event(0) | tag | {"tx_hash": f"0x{block}-{i}", "observed_at": moment.isoformat()})
            price *= 1 + direction * 0.0002
            rows.append({"observed_at": moment.isoformat(), "mark_price": price, "support": 1, "resistance": 2})
    result = information_coefficient(_IcStorage(rows, events), "BTCUSDT", horizon_cycles=96, trials=200)
    assert result["ic"] > 0.5
    assert result["p_positive"] <= result["p_value"]  # a strongly positive IC sits in the upper tail
    assert result["p_negative"] > 0.5
    assert result["independent_windows"] > 50
    assert result["mean_forward_after_accumulation"] > 0 > result["mean_forward_after_distribution"]


def test_information_coefficient_none_when_too_short():
    from whale_tracker.backtest.signal_ic import information_coefficient

    rows = [{"observed_at": (DAY + timedelta(minutes=15 * i)).isoformat(), "mark_price": 100.0} for i in range(200)]
    assert information_coefficient(_IcStorage(rows, []), "BTCUSDT", horizon_cycles=96) is None
