"""Historical replays exposing the SAME interface as simulation/*'s
generators (tick/market_snapshot/technical_snapshot/now, tick_events,
tick, tick_headlines), so simulate.run_cycle -- the real pipeline --
drives them unchanged.

The one rule every class here enforces: at simulated time `now`, only
data that had already happened by `now` is visible. No lookahead: the
current day's daily candle is rebuilt from 15m candles closed so far
(never Binance's finished daily candle for that day), funding is the
last SETTLED rate, Fear&Greed is the last value published at-or-before
`now`, and onchain events surface only once their block is mined."""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from datetime import UTC, datetime, timedelta
from typing import Any

from whale_tracker.sources.technical import DEFAULT_LOOKBACK_DAYS, compute_technical_snapshot


def _to_ms(moment: datetime) -> int:
    return int(moment.timestamp() * 1000)


class HistoricalDataGap(RuntimeError):
    """Raised when the replay has no data at all for a moment it needs --
    a real gap to surface, not something to paper over with a guess."""


class HistoricalMarketReplay:
    """One symbol's real price/funding/technical state, advanced one
    `tick()` per replayed observer cycle.

    open_interest is always 0.0: Binance only serves ~30 days of OI
    history, and nothing downstream of signal generation scores it
    (it's display-only in Kademe 2's prompt context)."""

    def __init__(
        self,
        symbol: str,
        *,
        klines_15m: list[list[Any]],
        daily_klines: list[list[Any]],
        funding_history: list[dict[str, Any]],
        start: datetime,
        lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    ) -> None:
        self.symbol = symbol
        self._k15 = sorted(klines_15m, key=lambda row: int(row[0]))
        self._k15_close_ms = [int(row[6]) for row in self._k15]
        self._daily = sorted(daily_klines, key=lambda row: int(row[0]))
        self._daily_open_ms = [int(row[0]) for row in self._daily]
        self._funding = sorted(funding_history, key=lambda f: f["funding_time_ms"])
        self._funding_ms = [f["funding_time_ms"] for f in self._funding]
        self._lookback_days = lookback_days
        self._now = start

    @property
    def now(self) -> datetime:
        return self._now

    def tick(self, *, minutes: int = 15) -> None:
        self._now += timedelta(minutes=minutes)

    def _closed_15m(self) -> list[list[Any]]:
        return self._k15[: bisect_right(self._k15_close_ms, _to_ms(self._now))]

    def market_snapshot(self) -> dict[str, Any]:
        closed = self._closed_15m()
        if not closed:
            raise HistoricalDataGap(f"{self.symbol}: {self._now.isoformat()} anında kapanmış 15m mum yok")
        funding_index = bisect_right(self._funding_ms, _to_ms(self._now))
        funding_rate = self._funding[funding_index - 1]["rate"] if funding_index else 0.0
        return {
            "symbol": self.symbol,
            "funding_rate": funding_rate,
            "open_interest": 0.0,
            "mark_price": float(closed[-1][4]),
            "observed_at": self._now.isoformat(),
        }

    def technical_snapshot(self) -> dict[str, Any]:
        day_start = self._now.replace(hour=0, minute=0, second=0, microsecond=0)
        day_start_ms = _to_ms(day_start)
        closed_days = self._daily[: bisect_left(self._daily_open_ms, day_start_ms)]
        today = [row for row in self._closed_15m() if int(row[0]) >= day_start_ms]

        # Production asks Binance for `lookback_days` daily candles, the
        # last of which is today's still-forming one -- mirror that shape.
        if today:
            partial = [
                day_start_ms, today[0][1],
                str(max(float(row[2]) for row in today)),
                str(min(float(row[3]) for row in today)),
                today[-1][4],
            ]
            rows = closed_days[-(self._lookback_days - 1):] + [partial]
        else:
            rows = closed_days[-self._lookback_days:]
        if not rows:
            raise HistoricalDataGap(f"{self.symbol}: {self._now.isoformat()} için günlük mum geçmişi yok")

        snapshot = compute_technical_snapshot(self.symbol, rows, lookback_days=self._lookback_days)
        snapshot["observed_at"] = self._now.isoformat()
        return snapshot


class HistoricalOnchainReplay:
    """Emits each real transfer once, on the first cycle at-or-after its
    block timestamp. observed_at is the block's own timestamp (not the
    cycle time), so warm-up events fetched from before the first cycle
    land in signal.py's 24h flow window at their real time instead of
    all bunching onto cycle one."""

    def __init__(self, events: list[dict[str, Any]]) -> None:
        self._events = sorted(events, key=lambda e: (e["block_timestamp"], e["block_number"], e["log_index"]))
        self._timestamps = [e["block_timestamp"] for e in self._events]
        self._cursor = 0

    def tick_events(self, *, observed_at: str | None = None) -> list[dict[str, Any]]:
        now_ts = int(datetime.fromisoformat(observed_at).timestamp())
        end = bisect_right(self._timestamps, now_ts)
        emitted = []
        for event in self._events[self._cursor:end]:
            payload = {k: v for k, v in event.items() if k != "block_timestamp"}
            payload["observed_at"] = datetime.fromtimestamp(event["block_timestamp"], UTC).isoformat()
            emitted.append(payload)
        self._cursor = end
        return emitted


class HistoricalSentimentReplay:
    """Latest daily Fear&Greed value published at-or-before `now` -- the
    same value production's limit=1 poll would have seen that moment."""

    def __init__(self, entries: list[dict[str, Any]]) -> None:
        self._entries = sorted(entries, key=lambda e: e["timestamp"])
        self._timestamps = [e["timestamp"] for e in self._entries]

    def tick(self, *, observed_at: str | None = None) -> dict[str, Any]:
        now_ts = int(datetime.fromisoformat(observed_at).timestamp())
        index = bisect_right(self._timestamps, now_ts)
        if not index:
            raise HistoricalDataGap(f"{observed_at} anında yayınlanmış Fear&Greed değeri yok")
        entry = self._entries[index - 1]
        return {
            "source": "fear_greed",
            "value": entry["value"],
            "label": entry["label"],
            "raw_json": entry,
            "observed_at": observed_at,
        }


class NoNewsReplay:
    """No free keyless historical news archive exists for the RSS feeds
    production reads, so the replay has no headlines at all -- see
    run.py's LIMITATIONS for what that does to the negative-news
    penalty."""

    def tick_headlines(self, *, max_per_cycle: int = 1, observed_at: str | None = None) -> list[dict[str, Any]]:
        return []
