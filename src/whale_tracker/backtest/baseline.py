"""Random-entry baseline: the actual edge test.

"Did the strategy beat BTC-hold" (evaluation.py, the plan's own section
9 criterion) can't separate signal quality from the exit rules: in a
rising market almost any long with a stop and a target makes money,
and in a falling one almost any loses. The question that isolates the
SIGNAL is: did entering WHEN the signal fired do better than entering
at random moments in the same period, with the exact same stop/target/
expiry rules? This replays that many times with random entry moments
and reports where the strategy's own result falls in that distribution.

Deliberately per-trade, not portfolio-level: Risk Guard's concurrency
cap and daily-loss brake change how many trades happen, not how good
each entry was, and are already measured separately (README's A/B)."""

from __future__ import annotations

import random
import statistics
from datetime import datetime, timedelta
from typing import Any

from whale_tracker.paper_trading import MAX_HOLD_DAYS, compute_exit_levels
from whale_tracker.sources.proposal import _compute_stop_loss

_MAX_REDRAWS = 200


def _simulate_entry(history: list[dict[str, Any]], index: int) -> float | None:
    """pnl_pct of a long entered at history[index] under the strategy's
    own rules, or None if the setup is broken or never closes before the
    data ends (the strategy's own evaluation only counts closed trades)."""
    entry = history[index]
    stop = _compute_stop_loss({"support": entry["support"]})
    exits = compute_exit_levels(
        {"action": "long_candidate", "stop_loss_price": stop}, entry["mark_price"], {"resistance": entry["resistance"]},
    )
    if exits is None:
        return None
    stop_loss_price, take_profit_price = exits
    expires_at = entry["moment"] + timedelta(days=MAX_HOLD_DAYS)
    # Same order as paper_trading.check_and_close_positions: stop first,
    # then target, then expiry.
    for later_index in range(index + 1, len(history)):
        later = history[later_index]
        price = later["mark_price"]
        if price <= stop_loss_price:
            exit_price = stop_loss_price
        elif price >= take_profit_price:
            exit_price = take_profit_price
        elif later["moment"] >= expires_at:
            exit_price = price
        else:
            continue
        return (exit_price - entry["mark_price"]) / entry["mark_price"]
    return None


def random_entry_baseline(
    storage: Any, closed_positions: list[dict[str, Any]], *, trials: int = 500, seed: int = 0,
) -> dict[str, Any] | None:
    """For each trial, draw one random entry per strategy trade (same
    symbol), and record the trial's mean pnl_pct. Returns None when the
    strategy closed no trades -- nothing to compare against."""
    if not closed_positions:
        return None
    rng = random.Random(seed)
    histories = {
        symbol: [
            {**row, "moment": datetime.fromisoformat(row["observed_at"])}
            for row in storage.price_and_levels_history(symbol)
        ]
        for symbol in {p.get("symbol", "BTCUSDT") for p in closed_positions}
    }

    trial_means: list[float] = []
    for _ in range(trials):
        pnls: list[float] = []
        for position in closed_positions:
            history = histories[position.get("symbol", "BTCUSDT")]
            for _ in range(_MAX_REDRAWS):
                pnl = _simulate_entry(history, rng.randrange(len(history)))
                if pnl is not None:
                    pnls.append(pnl)
                    break
        if pnls:
            trial_means.append(statistics.mean(pnls))

    strategy_mean = statistics.mean(p["pnl_pct"] for p in closed_positions)
    at_least_as_good = sum(1 for m in trial_means if m >= strategy_mean)
    return {
        "trials": len(trial_means),
        "trades_per_trial": len(closed_positions),
        "strategy_mean_pnl_pct": round(strategy_mean, 5),
        "random_mean_pnl_pct": round(statistics.mean(trial_means), 5),
        "random_stdev_of_means": round(statistics.pstdev(trial_means), 5),
        # Fraction of random trials that did at least as well as the
        # strategy -- a one-sided permutation-style p-value. Small (<0.05)
        # would mean the signal's timing genuinely added something.
        "p_value": round(at_least_as_good / len(trial_means), 4),
    }
