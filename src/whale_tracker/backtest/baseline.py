"""Random-entry baseline: the actual edge test.

"Did the strategy beat BTC-hold" (evaluation.py, the plan's own section
9 criterion) can't separate signal quality from the exit rules: in a
rising market almost any long with a stop and a target makes money,
and in a falling one almost any loses. The question that isolates the
SIGNAL is: did entering WHEN the signal fired do better than entering
at random moments in the same period, with the exact same stop/target/
expiry rules? This replays that many times with random entry moments
and reports where the strategy's own result falls in that distribution.

Random moments = a CIRCULAR TIME SHIFT of the strategy's own entries,
not independent draws. First version drew each random entry
independently and, validated against the no-edge null simulation
(calibrate.py --edge-strength 0), flagged a "significant edge" in 22%
of runs instead of the ~5% a calibrated test should: the strategy's
trades cluster in time (one signal opens 2-3 overlapping positions with
correlated outcomes), so independent draws understate how much a
random set of entries with the SAME clustering varies. Shifting every
entry by one shared random offset preserves that clustering (and the
BTC/ETH cross-symbol timing) exactly -- only WHEN the cluster happens
is randomized. Shifts smaller than MIN_SHIFT on either side are
excluded so a "random" trial can't largely reproduce the real one.

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

# One day of 15-minute cycles: a shift shorter than this mostly re-tests
# the strategy's own entries (and their overlapping outcomes).
MIN_SHIFT_CYCLES = 96


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
    min_shift_cycles: int = MIN_SHIFT_CYCLES,
) -> dict[str, Any] | None:
    """For each trial, shift ALL of the strategy's entry moments by one
    shared random offset (wrapping around the period) and record the
    mean pnl_pct of the shifted entries that form a valid setup and
    close. Returns None when there's nothing to compare -- no closed
    trades, or a period too short to shift meaningfully."""
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
    index_of = {symbol: {row["observed_at"]: i for i, row in enumerate(h)} for symbol, h in histories.items()}
    entries: list[tuple[str, int]] = []
    for position in closed_positions:
        symbol = position.get("symbol", "BTCUSDT")
        if position["opened_at"] in index_of[symbol]:
            entries.append((symbol, index_of[symbol][position["opened_at"]]))
    # BTC and ETH histories come from the same cycles, so one shared
    # length (the shorter, defensively) keeps one offset meaning the
    # same moment for both.
    length = min(len(h) for h in histories.values())
    if not entries or length <= 2 * min_shift_cycles:
        return None

    trial_means: list[float] = []
    for _ in range(trials):
        shift = rng.randrange(min_shift_cycles, length - min_shift_cycles)
        pnls = [
            pnl for symbol, index in entries
            if (pnl := _simulate_entry(histories[symbol], (index + shift) % length)) is not None
        ]
        if pnls:
            trial_means.append(statistics.mean(pnls))
    if not trial_means:
        return None

    strategy_mean = statistics.mean(p["pnl_pct"] for p in closed_positions)
    at_least_as_good = sum(1 for m in trial_means if m >= strategy_mean)
    return {
        "method": "circular_shift",
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
