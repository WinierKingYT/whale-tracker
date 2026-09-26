"""Signal-level edge test: does the 24h net exchange flow signal.py
scores actually predict forward returns?

The trade-level test (baseline.py) turned out to say little about the
SIGNAL on real data: the flow gate fires on nearly every cycle (5,760
candidates in a 2,880-cycle month), so when positions actually open is
decided mostly by Risk Guard's 3-slot cap freeing up, not by signal
strength. This skips the trading layer and asks the direct question at
every cycle: rank-correlate "net outflow over the last 24h" with the
next H hours' return (Spearman information coefficient).

Significance uses the same circular-shift idea as baseline.py (shift the
return series against the signal by >= the horizon), because both
series are heavily autocorrelated -- overlapping 72h windows, a signal
that persists for days. That autocorrelation is also why the result
carries its own power estimate: the number of INDEPENDENT windows is
roughly period / horizon, not the cycle count, and with a whale signal
that persists for days a month holds only ~10 of them. Validated on
planted-edge simulations (calibrate.py's regime): at 30 days even an
unrealistically strong edge was not reliably detected -- so a "no edge"
result here is only meaningful when detectable_ic is small."""

from __future__ import annotations

import math
import random
import statistics
from datetime import datetime, timedelta
from typing import Any

from whale_tracker.flow import exchange_flow_contribution
from whale_tracker.sources.onchain import load_wallet_registry

FLOW_WINDOW_HOURS = 24


def rolling_net_inflow(events: list[dict[str, Any]], times: list[datetime], *, hours: int = FLOW_WINDOW_HOURS) -> list[float]:
    """Net inflow over (t - hours, t] at each time in `times` (sorted),
    in one pass -- the per-cycle equivalent of signal.py's window."""
    registry = load_wallet_registry()
    flows = sorted(
        (datetime.fromisoformat(e["observed_at"]), c)
        for e in events if (c := exchange_flow_contribution(e, registry))
    )
    window = timedelta(hours=hours)
    result: list[float] = []
    low = high = 0
    running = 0.0
    for moment in times:
        while high < len(flows) and flows[high][0] <= moment:
            running += flows[high][1]
            high += 1
        while low < high and flows[low][0] < moment - window:
            running -= flows[low][1]
            low += 1
        result.append(running)
    return result


def _ranks(values: list[float]) -> list[float]:
    order = sorted(range(len(values)), key=values.__getitem__)
    ranks = [0.0] * len(values)
    for rank, index in enumerate(order):
        ranks[index] = float(rank)
    return ranks


def _pearson(x: list[float], y: list[float]) -> float:
    mean_x, mean_y = statistics.fmean(x), statistics.fmean(y)
    cov = sum((a - mean_x) * (b - mean_y) for a, b in zip(x, y))
    var_x = sum((a - mean_x) ** 2 for a in x)
    var_y = sum((b - mean_y) ** 2 for b in y)
    return cov / math.sqrt(var_x * var_y) if var_x and var_y else 0.0


def information_coefficient(
    storage: Any, symbol: str, *, horizon_cycles: int, cycle_minutes: int = 15, trials: int = 500, seed: int = 0,
) -> dict[str, Any] | None:
    """Spearman IC between the accumulation signal (24h net OUTFLOW) and
    the return over the next `horizon_cycles`, with a two-sided
    circular-shift p-value. None if the period is too short to shift."""
    history = storage.price_and_levels_history(symbol)
    count = len(history) - horizon_cycles
    if count <= 2 * horizon_cycles:
        return None
    times = [datetime.fromisoformat(row["observed_at"]) for row in history]
    prices = [row["mark_price"] for row in history]
    signal = [-net for net in rolling_net_inflow(storage.recent_onchain_events(limit=10**7), times)][:count]
    forward = [prices[i + horizon_cycles] / prices[i] - 1 for i in range(count)]

    signal_ranks, forward_ranks = _ranks(signal), _ranks(forward)
    ic = _pearson(signal_ranks, forward_ranks)
    rng = random.Random(seed)
    null = []
    for _ in range(trials):
        shift = rng.randrange(horizon_cycles, count - horizon_cycles)
        null.append(_pearson(signal_ranks, forward_ranks[shift:] + forward_ranks[:shift]))

    independent_windows = count / horizon_cycles
    accumulation = [f for s, f in zip(signal, forward) if s > 0]
    distribution = [f for s, f in zip(signal, forward) if s < 0]
    return {
        "symbol": symbol,
        "horizon_hours": horizon_cycles * cycle_minutes / 60,
        "ic": round(ic, 4),
        "p_value": round(sum(1 for z in null if abs(z) >= abs(ic)) / trials, 4),
        # One-sided tails, for a hypothesis written down before looking
        # (docs/preregistration/): p_negative is how often a shifted null
        # IC is at least as negative as the observed one.
        "p_negative": round(sum(1 for z in null if z <= ic) / trials, 4),
        "p_positive": round(sum(1 for z in null if z >= ic) / trials, 4),
        "independent_windows": round(independent_windows, 1),
        # Rough 2-sigma detection floor: an IC smaller than this can't be
        # told apart from noise with this many independent windows.
        "detectable_ic": round(2 / math.sqrt(independent_windows), 3),
        "mean_forward_after_accumulation": statistics.fmean(accumulation) if accumulation else None,
        "mean_forward_after_distribution": statistics.fmean(distribution) if distribution else None,
    }
