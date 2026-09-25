"""Position sizing: the one rule paper trading and Aşama 5 both use.

Section 7's "İşlem başına maksimum risk: sermayenin %1'i" is ACCOUNT RISK:
if the stop is hit, the loss is 1% of capital. It is not "a position
worth 1% of capital" -- that sizing risked only ~0.02% of capital on a
2% stop, so paper results said nothing about the plan's actual risk rule.

    risk_budget_usd   = capital * ACCOUNT_RISK_PCT
    stop_distance_pct = (entry - stop) / entry
    position_size_usd = risk_budget_usd / stop_distance_pct

capped at MAX_NOTIONAL_PCT of capital (no leverage), so a very tight stop
can't produce an oversized position -- in that case the realized risk is
below the budget, never above."""

from __future__ import annotations

ACCOUNT_RISK_PCT = 0.01
MAX_NOTIONAL_PCT = 1.0


def position_size_usd(
    capital_usd: float, entry_price: float, stop_loss_price: float, *, risk_pct: float = ACCOUNT_RISK_PCT,
    available_notional_usd: float | None = None,
) -> float | None:
    """Notional size for a long, or None when sizing is impossible
    (no capital, stop not below entry, no notional room left).
    `available_notional_usd` is what the account has not already committed
    to open positions -- total exposure never exceeds capital."""
    if capital_usd <= 0 or entry_price <= 0 or not (0 < stop_loss_price < entry_price):
        return None
    stop_distance_pct = (entry_price - stop_loss_price) / entry_price
    size = capital_usd * risk_pct / stop_distance_pct
    cap = capital_usd * MAX_NOTIONAL_PCT
    if available_notional_usd is not None:
        cap = min(cap, available_notional_usd)
    if cap <= 0:
        return None
    return round(min(size, cap), 2)
