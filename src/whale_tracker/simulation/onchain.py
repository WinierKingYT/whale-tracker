"""Synthetic whale-transfer generator -- no real RPC calls. Reuses
sources/onchain.py's REAL known-wallet tagging (_load_known_wallets, the
same data/known-exchange-wallets.json production reads) so a simulated
event is classified into known/unknown/DEX/flagged exactly like a real
one would be, not by a parallel reimplementation of that logic."""

from __future__ import annotations

import random
from datetime import UTC, datetime
from typing import Any

from whale_tracker.simulation.regime import LatentRegime
from whale_tracker.sources.onchain import TRACKED_TOKENS, _load_known_wallets

# Roughly matches amounts actually observed in this project's real data
# this session ($1M-$100M+, most modest, occasional huge) -- a lognormal
# distribution, not fit to a real statistical model. mean/stddev are of
# the underlying normal (i.e. of ln(amount)), so the resulting amount
# distribution is heavy-tailed on purpose.
_AMOUNT_LOG_MEAN = 14.5
_AMOUNT_LOG_STDDEV = 1.3

# Chance a synthetic transfer's counterparty is a real address from
# known-exchange-wallets.json rather than a random unknown one -- keeps
# the report's known/unknown grouping realistically exercised.
_KNOWN_COUNTERPARTY_PROBABILITY = 0.3


def _random_address(rng: random.Random) -> str:
    return "0x" + "".join(rng.choice("0123456789abcdef") for _ in range(40))


class OnchainSimulator:
    def __init__(
        self, *, seed: int | None = None, events_per_cycle_mean: float = 1.5, min_usd: float = 1_000_000.0,
        regime: LatentRegime | None = None, flow_bias: float = 0.0,
    ) -> None:
        """`regime` + `flow_bias` plant a known edge (see
        simulation/regime.py): each event is, with probability
        flow_bias x |regime|, rewritten into a directional exchange flow
        -- an outflow from an exchange when the regime is positive
        (accumulation), an inflow when negative. Both default off."""
        self._rng = random.Random(seed)
        self._known_wallets = _load_known_wallets()
        self._known_addresses = list(self._known_wallets.keys())
        # Exactly the wallets signal.py's flow aggregation counts.
        self._exchange_addresses = [
            address for address, label in self._known_wallets.items() if not label.startswith(("DEX:", "⚠"))
        ]
        self._events_per_cycle_mean = events_per_cycle_mean
        self._min_usd = min_usd
        self._regime = regime
        self._flow_bias = flow_bias
        self._block_number = 20_000_000
        self._tx_counter = 0

    def tick_events(self, *, observed_at: str | None = None) -> list[dict[str, Any]]:
        observed_at = observed_at or datetime.now(UTC).isoformat()
        # A crude Poisson-ish draw: ten Bernoulli trials each with
        # probability mean/10 -- good enough for "usually 0-2, occasionally
        # more," not a real Poisson process.
        count = sum(1 for _ in range(10) if self._rng.random() < self._events_per_cycle_mean / 10)
        events: list[dict[str, Any]] = []
        for _ in range(count):
            self._block_number += self._rng.randint(1, 20)
            self._tx_counter += 1
            token = self._rng.choice([entry[0] for entry in TRACKED_TOKENS])
            amount = self._rng.lognormvariate(_AMOUNT_LOG_MEAN, _AMOUNT_LOG_STDDEV)
            if amount < self._min_usd:
                continue
            from_addr = self._random_counterparty()
            to_addr = self._random_counterparty()
            if self._regime is not None and self._exchange_addresses:
                from_addr, to_addr = self._apply_regime_tilt(from_addr, to_addr, observed_at)
            events.append({
                "tx_hash": f"0xsim{self._tx_counter:08d}",
                "log_index": 0,
                "block_number": self._block_number,
                "token": token,
                "from_address": from_addr,
                "to_address": to_addr,
                "amount_usd_estimate": round(amount, 2),
                "raw_amount": str(int(amount * 10**6)),
                "from_known_exchange": self._known_wallets.get(from_addr.lower()),
                "to_known_exchange": self._known_wallets.get(to_addr.lower()),
                "observed_at": observed_at,
            })
        return events

    def _apply_regime_tilt(self, from_addr: str, to_addr: str, observed_at: str) -> tuple[str, str]:
        regime_value = self._regime.value_at(datetime.fromisoformat(observed_at))
        if self._rng.random() >= min(1.0, self._flow_bias * abs(regime_value)):
            return from_addr, to_addr
        exchange = self._rng.choice(self._exchange_addresses)
        unknown = _random_address(self._rng)
        return (exchange, unknown) if regime_value > 0 else (unknown, exchange)

    def _random_counterparty(self) -> str:
        if self._known_addresses and self._rng.random() < _KNOWN_COUNTERPARTY_PROBABILITY:
            return self._rng.choice(self._known_addresses)
        return _random_address(self._rng)
