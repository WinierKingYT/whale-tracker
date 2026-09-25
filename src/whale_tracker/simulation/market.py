"""Synthetic price/funding/open-interest generator. Runs the REAL
sources/technical.py computation (compute_technical_snapshot) against a
synthetic candle history rather than a parallel reimplementation, so a
simulation exercises the exact support/resistance/trend logic production
uses -- only the input data is fake, not the math.

Price follows geometric Brownian motion (daily drift + volatility);
funding rate is a bounded mean-reverting random walk; open interest is a
slow random walk. This is "realistic enough to exercise every downstream
code path with plausible numbers," not a real market microstructure
model -- not calibrated against actual BTC/ETH statistics, revisit if a
simulated run's plausibility is ever actually in question."""

from __future__ import annotations

import math
import random
from datetime import UTC, datetime, timedelta
from typing import Any

from whale_tracker.simulation.regime import LatentRegime
from whale_tracker.sources.technical import DEFAULT_LOOKBACK_DAYS, compute_technical_snapshot

DEFAULT_START_PRICE = {"BTCUSDT": 70_000.0, "ETHUSDT": 3_000.0}
DAILY_VOLATILITY = 0.03
DAILY_DRIFT = 0.0  # no assumed direction -- a fair random walk by default
FUNDING_VOLATILITY = 0.00005
FUNDING_MEAN_REVERSION = 0.1
OI_DAILY_VOLATILITY = 0.02


class _DailyCandle:
    __slots__ = ("close", "high", "low", "open")

    def __init__(self, open_price: float) -> None:
        self.open = self.high = self.low = self.close = open_price

    def update(self, price: float) -> None:
        self.high = max(self.high, price)
        self.low = min(self.low, price)
        self.close = price

    def as_kline_row(self) -> list[Any]:
        # Binance's raw kline shape: [open_time, open, high, low, close, ...].
        # compute_technical_snapshot() only reads indices 1-4.
        return [0, str(self.open), str(self.high), str(self.low), str(self.close), "0", 0, "0", 0, "0", "0", "0"]


class MarketSimulator:
    """One symbol's simulated price/funding/OI state, advanced one
    `tick()` per simulated observer cycle. Seeded for reproducibility."""

    def __init__(
        self,
        symbol: str,
        *,
        seed: int | None = None,
        start_price: float | None = None,
        daily_volatility: float = DAILY_VOLATILITY,
        daily_drift: float = DAILY_DRIFT,
        lookback_days: int = DEFAULT_LOOKBACK_DAYS,
        regime: LatentRegime | None = None,
        edge_daily_drift: float = 0.0,
    ) -> None:
        """`regime` + `edge_daily_drift` plant a known edge (see
        simulation/regime.py): extra daily drift = edge_daily_drift x the
        regime's current value. Both default off -- the unmodified
        no-drift random walk."""
        self.symbol = symbol
        self._rng = random.Random(seed)
        self._price = start_price if start_price is not None else DEFAULT_START_PRICE.get(symbol, 100.0)
        self._daily_volatility = daily_volatility
        self._daily_drift = daily_drift
        self._regime = regime
        self._edge_daily_drift = edge_daily_drift
        self._lookback_days = lookback_days
        self._funding_rate = 0.0
        self._open_interest = self._price * 1_000.0
        self._now = datetime.now(UTC)
        self._candles: list[_DailyCandle] = [_DailyCandle(self._price)]

    def tick(self, *, minutes: int = 15) -> None:
        """Advance simulated time by `minutes`: one GBM price step, one
        funding-rate step, one OI step, and roll the daily candle window
        forward when simulated time crosses a day boundary."""
        dt_days = minutes / (24 * 60)
        shock = self._rng.gauss(0, 1)
        daily_drift = self._daily_drift
        if self._regime is not None:
            daily_drift += self._edge_daily_drift * self._regime.value_at(self._now)
        drift_term = (daily_drift - 0.5 * self._daily_volatility**2) * dt_days
        vol_term = self._daily_volatility * math.sqrt(dt_days) * shock
        self._price = max(0.01, self._price * math.exp(drift_term + vol_term))

        funding_shock = self._rng.gauss(0, FUNDING_VOLATILITY)
        self._funding_rate = self._funding_rate * (1 - FUNDING_MEAN_REVERSION) + funding_shock

        oi_shock = self._rng.gauss(0, OI_DAILY_VOLATILITY * math.sqrt(dt_days))
        self._open_interest = max(1.0, self._open_interest * (1 + oi_shock))

        self._candles[-1].update(self._price)
        new_now = self._now + timedelta(minutes=minutes)
        if new_now.date() != self._now.date():
            self._candles.append(_DailyCandle(self._price))
            if len(self._candles) > self._lookback_days + 5:
                self._candles.pop(0)
        self._now = new_now

    def market_snapshot(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "funding_rate": round(self._funding_rate, 6),
            "open_interest": round(self._open_interest, 2),
            "mark_price": round(self._price, 2),
            "observed_at": self._now.isoformat(),
        }

    def technical_snapshot(self) -> dict[str, Any]:
        klines = [candle.as_kline_row() for candle in self._candles[-self._lookback_days :]]
        snapshot = compute_technical_snapshot(self.symbol, klines, lookback_days=self._lookback_days)
        snapshot["observed_at"] = self._now.isoformat()
        return snapshot

    @property
    def now(self) -> datetime:
        return self._now
