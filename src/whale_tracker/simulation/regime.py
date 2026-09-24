"""A hidden "whale regime" shared by MarketSimulator and OnchainSimulator,
used to plant a KNOWN edge into a simulation on purpose.

Why: the default simulation is a no-drift random walk with no
exploitable structure, so it can only ever show the pipeline has no edge
there -- which says nothing about whether the pipeline, or the backtest's
random-entry test, could detect an edge that DID exist. Planting one
makes both testable: when the regime is positive, whales accumulate
(onchain flow tilts toward exchange outflows) AND price drifts up; when
negative, the reverse. The regime is persistent (mean-reverting with a
multi-day half-life), so today's flow genuinely predicts the next days'
drift -- exactly the relationship signal.py's onchain_flow component
assumes exists in the real market.

Advances lazily to whatever time it's asked about, in fixed 15-minute
steps, so it stays deterministic for a seed regardless of which
simulator queries it first in a cycle."""

from __future__ import annotations

import math
import random
from datetime import datetime, timedelta

_STEP = timedelta(minutes=15)
DEFAULT_HALF_LIFE_DAYS = 3.0
# Stationary stddev of the regime before clipping to [-1, 1].
DEFAULT_STATIONARY_STDDEV = 0.5


class LatentRegime:
    def __init__(
        self, *, seed: int | None = None, half_life_days: float = DEFAULT_HALF_LIFE_DAYS,
        stationary_stddev: float = DEFAULT_STATIONARY_STDDEV,
    ) -> None:
        self._rng = random.Random(seed)
        self._theta = math.log(2) / half_life_days
        # OU stationary variance is sigma^2 / (2 * theta).
        self._sigma = stationary_stddev * math.sqrt(2 * self._theta)
        self._value = 0.0
        self._time: datetime | None = None

    def value_at(self, moment: datetime) -> float:
        if self._time is None:
            self._time = moment
        dt_days = _STEP.total_seconds() / 86_400
        while self._time + _STEP <= moment:
            shock = self._rng.gauss(0, 1) * self._sigma * math.sqrt(dt_days)
            self._value = max(-1.0, min(1.0, self._value - self._theta * self._value * dt_days + shock))
            self._time += _STEP
        return self._value
