"""Execution model: what a trade actually returns after costs.

Paper trading and the random-entry baseline both used to assume a free,
perfect fill: enter exactly at the mark, exit exactly at the stop even
when the next observed price had already gapped far below it, no fees,
no spread. With a small measured edge those assumptions alone can flip
the sign of the result, so both now go through this one model -- the
strategy and its baseline pay identical costs.

Market orders (entry, stop, expiry) cross half the spread and slip;
the take-profit is a resting limit order: filled at its level, no
slippage, and conservatively no price improvement on a gap up. A stop is
filled at the WORSE of the stop level and the first observed price at or
below it -- we only see prices once per cycle, and a gap through the
stop is exactly the case the free-fill model hid.

Constants are conservative first-pass estimates for Binance USDⓈ-M
BTC/ETH perpetuals at small size (taker fee tier 0), not calibrated
against our own fills (there are none yet)."""

from __future__ import annotations

TAKER_FEE_PCT = 0.0005     # per side
MAKER_FEE_PCT = 0.0002     # per side, the resting take-profit
HALF_SPREAD_PCT = 0.0001
SLIPPAGE_PCT = 0.0002

EXIT_STOP = "stopped_out"
EXIT_TARGET = "take_profit"
EXIT_EXPIRY = "expired"


def entry_fill(mark_price: float) -> float:
    return mark_price * (1 + HALF_SPREAD_PCT + SLIPPAGE_PCT)


def exit_fill(kind: str, level: float, observed_price: float) -> float:
    if kind == EXIT_TARGET:
        return level
    if kind == EXIT_STOP:
        return min(level, observed_price) * (1 - HALF_SPREAD_PCT - SLIPPAGE_PCT)
    if kind == EXIT_EXPIRY:
        return observed_price * (1 - HALF_SPREAD_PCT - SLIPPAGE_PCT)
    raise ValueError(f"unknown exit kind: {kind}")


def net_return_pct(entry_mark: float, kind: str, level: float, observed_price: float) -> tuple[float, float]:
    """(exit_fill_price, net pnl fraction of notional) for a long entered
    at `entry_mark`, after spread, slippage and both sides' fees."""
    entry = entry_fill(entry_mark)
    exit_price = exit_fill(kind, level, observed_price)
    exit_fee = MAKER_FEE_PCT if kind == EXIT_TARGET else TAKER_FEE_PCT
    return exit_price, (exit_price - entry) / entry - TAKER_FEE_PCT - exit_fee
