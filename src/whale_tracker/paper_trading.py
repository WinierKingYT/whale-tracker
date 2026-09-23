"""Asama 3: Paper trading (see docs/PROJECT-PLAN.md section 8 -- "Onerileri
sahte parayla uygular; birkac hafta sonuclar olculur"). Opens a simulated
position from a Kademe 3 "long_candidate" proposal and tracks it against
real market prices until it hits stop-loss, take-profit, or times out.

No real money, no exchange client, no order ever placed -- same "Kritik
sinir" boundary as every other module here (see README.md). This is a
bookkeeping exercise against real price data, nothing more.

Like proposal.py, the exit levels are code-derived, not AI-proposed:
- stop_loss_price already comes from proposal.py (support-derived).
- take_profit_price is this module's own symmetric counterpart, derived
  from the technical snapshot's resistance level -- same reasoning as
  the stop-loss buffer, not calibrated against real trade history yet
  (there is none), revisit once positions actually close.
- MAX_HOLD_DAYS enforces section 6's own stated style ("saatlik-gunluk
  pozisyonlar, swing") -- a proposal is not meant to sit open indefinitely
  waiting for either exit price."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

# First-pass paper capital -- not real money, exists only so position
# sizing (the 1%-of-capital rule from proposal.py) has a concrete dollar
# base to size against. Revisit once this project has weeks of paper
# trades to calibrate against, same caveat as every other *_PCT constant
# in this codebase.
VIRTUAL_CAPITAL_USD = 10_000.0

# Mirrors proposal.py's STOP_LOSS_SUPPORT_BUFFER_PCT: take profit slightly
# below resistance rather than exactly at it, since price often stalls or
# reverses just short of a resistance level in practice.
TAKE_PROFIT_RESISTANCE_BUFFER_PCT = 0.005

# Section 6: "Saatlik-gunluk pozisyonlar (swing)" -- a position that has
# hit neither exit after a week is stale for this trading style, not a
# thesis worth holding open indefinitely.
MAX_HOLD_DAYS = 7


def open_position(
    candidate_id: int, proposal: dict[str, Any], market_price: float, technical: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Open a paper position from a Kademe 3 long_candidate proposal.
    Returns None (does not open) when the risk/reward setup doesn't make
    sense -- e.g. price already through the stop-loss or past the
    take-profit level -- rather than opening a broken position."""
    if proposal["action"] != "long_candidate":
        return None
    if not technical or not technical.get("resistance"):
        return None

    stop_loss_price = proposal["stop_loss_price"]
    take_profit_price = round(technical["resistance"] * (1 - TAKE_PROFIT_RESISTANCE_BUFFER_PCT), 2)
    if not (stop_loss_price < market_price < take_profit_price):
        return None  # broken setup: already past an exit level, don't open it

    return {
        "signal_candidate_id": candidate_id,
        "entry_price": market_price,
        "stop_loss_price": stop_loss_price,
        "take_profit_price": take_profit_price,
        "position_size_usd": round(VIRTUAL_CAPITAL_USD * proposal["max_position_size_pct"], 2),
        "status": "open",
        "opened_at": datetime.now(UTC).isoformat(),
    }


def _pnl(entry_price: float, exit_price: float, position_size_usd: float) -> tuple[float, float]:
    pnl_pct = (exit_price - entry_price) / entry_price
    return round(position_size_usd * pnl_pct, 2), round(pnl_pct, 4)


def check_and_close_positions(storage: Any, current_price: float) -> list[dict[str, Any]]:
    """Check every open paper position against the current market price;
    close and record any that hit stop-loss, take-profit, or MAX_HOLD_DAYS.
    Returns the list of positions closed this call (empty most cycles)."""
    now = datetime.now(UTC)
    closed: list[dict[str, Any]] = []
    for position in storage.open_paper_positions():
        opened_at = datetime.fromisoformat(position["opened_at"])
        if current_price <= position["stop_loss_price"]:
            exit_price, status = position["stop_loss_price"], "stopped_out"
        elif current_price >= position["take_profit_price"]:
            exit_price, status = position["take_profit_price"], "take_profit"
        elif now - opened_at >= timedelta(days=MAX_HOLD_DAYS):
            exit_price, status = current_price, "expired"
        else:
            continue

        pnl_usd, pnl_pct = _pnl(position["entry_price"], exit_price, position["position_size_usd"])
        storage.close_paper_position(
            position["id"], exit_price=exit_price, status=status,
            closed_at=now.isoformat(), pnl_usd=pnl_usd, pnl_pct=pnl_pct,
        )
        closed.append({**position, "exit_price": exit_price, "status": status, "pnl_usd": pnl_usd, "pnl_pct": pnl_pct})
    return closed
