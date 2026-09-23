"""Synthetic Fear & Greed index -- a bounded mean-reverting random walk
in [0, 100], not a real sentiment model. Label bands mirror
Alternative.me's own published bands (roughly), same numeric thresholds
signal.py's _score_sentiment already treats as fear/neutral/greed."""

from __future__ import annotations

import random
from datetime import UTC, datetime
from typing import Any

_LABEL_BANDS = (
    (0.0, 25.0, "Extreme Fear"),
    (25.0, 45.0, "Fear"),
    (45.0, 55.0, "Neutral"),
    (55.0, 75.0, "Greed"),
    (75.0, 101.0, "Extreme Greed"),
)


def _label_for(value: float) -> str:
    for low, high, label in _LABEL_BANDS:
        if low <= value < high:
            return label
    return "Neutral"


class SentimentSimulator:
    def __init__(self, *, seed: int | None = None, start_value: float = 50.0, shock_stddev: float = 4.0) -> None:
        self._rng = random.Random(seed)
        self._value = start_value
        self._shock_stddev = shock_stddev

    def tick(self, *, observed_at: str | None = None) -> dict[str, Any]:
        shock = self._rng.gauss(0, self._shock_stddev)
        reversion = (50.0 - self._value) * 0.05
        self._value = min(100.0, max(0.0, self._value + shock + reversion))
        # Round once, then label from the rounded value -- labeling from
        # the unrounded value could disagree with the value actually
        # returned right at a band boundary (e.g. unrounded 44.96 labels
        # "Fear" but rounds to a displayed 45.0, which reads as "Neutral").
        rounded_value = round(self._value, 1)
        return {
            "source": "fear_greed",
            "value": rounded_value,
            "label": _label_for(rounded_value),
            "raw_json": {"simulated": True},
            "observed_at": observed_at or datetime.now(UTC).isoformat(),
        }
