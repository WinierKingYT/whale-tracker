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
  waiting for either exit price.

TRIED AND REVERTED (calibrate.py, base_seed=200, 10 runs x 800 cycles):
this resistance-only target produces a real, consistent avg-win-much-
smaller-than-avg-loss pattern (+0.81% vs -3.59% across the batch) --
looks like a textbook case for a standard reward:risk floor (target =
max(resistance, entry + 2x the stop-loss distance)). Measured it anyway
instead of assuming the textbook heuristic transfers: win rate collapsed
from 93.8% to 12.6% and net strategy return went from +0.95% to -1.61%.
In a no-drift random-walk price path, a farther target is simply much
less likely to ever be touched before the stop or MAX_HOLD_DAYS -- the
size-per-win improvement did not come close to compensating for how much
rarer wins became. The original resistance-only design's high hit-rate
was doing more real work than its small win size looked like it should.
Don't re-apply this exact fix without re-measuring; a real, better fix
here would need to change WHY the win rate is so tied to target distance
(e.g. actual trend/momentum modeling), not just move the target."""

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

# Section 7, "Risk Kurallari (Degismez Anayasa)" -- these two were not
# enforced ANYWHERE before, not even in paper trading: "Ayni anda en fazla
# 2-3 acik pozisyon" (upper bound taken as the cap) and "Gunluk maksimum
# kayip %3 -> asilirsa sistem o gun durur." The plan's own AI-tier table
# calls this the "Risk Guard (kod) -- her islemde, son soz" role -- final
# say on every trade, not negotiable, not AI-adjustable, not something a
# good trade idea overrides. Global across all tracked symbols (the plan
# doesn't say per-symbol) and checked before every new position, paper or
# otherwise, so the same guard is already proven correct once Asama 5
# needs it for real.
MAX_CONCURRENT_POSITIONS = 3
MAX_DAILY_LOSS_PCT = 0.03


def _daily_pnl_pct(storage: Any, *, now: datetime) -> float:
    """Sum of pnl_usd for positions closed on `now`'s UTC calendar date,
    as a fraction of VIRTUAL_CAPITAL_USD. Positive = net winning day so
    far, negative = net losing day."""
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    total_usd = 0.0
    for position in storage.all_paper_positions():
        if position["status"] == "open" or not position.get("closed_at"):
            continue
        if datetime.fromisoformat(position["closed_at"]) >= day_start:
            total_usd += position["pnl_usd"]
    return total_usd / VIRTUAL_CAPITAL_USD


def risk_guard_blocks_new_position(storage: Any, *, now: datetime | None = None) -> str | None:
    """Returns a human-readable reason if the plan's own fixed risk rules
    block opening ANY new position right now, else None. Call this before
    open_position() -- it stays a separate, independently-testable check
    rather than folded into open_position() itself, so a caller can log
    exactly why a otherwise-valid strong candidate didn't open, same
    transparency principle as every other skip-reason in this codebase."""
    now = now or datetime.now(UTC)
    if len(storage.open_paper_positions()) >= MAX_CONCURRENT_POSITIONS:
        return f"eşzamanlı pozisyon tavanı doldu (>={MAX_CONCURRENT_POSITIONS})"
    daily_pnl_pct = _daily_pnl_pct(storage, now=now)
    if daily_pnl_pct <= -MAX_DAILY_LOSS_PCT:
        return f"günlük kayıp sınırı aşıldı ({daily_pnl_pct:+.2%}, sınır {-MAX_DAILY_LOSS_PCT:.0%})"
    return None


def open_position(
    candidate_id: int, proposal: dict[str, Any], market_price: float, technical: dict[str, Any] | None,
    *, symbol: str = "BTCUSDT", now: datetime | None = None,
) -> dict[str, Any] | None:
    """Open a paper position from a Kademe 3 long_candidate proposal.
    Returns None (does not open) when the risk/reward setup doesn't make
    sense -- e.g. price already through the stop-loss or past the
    take-profit level -- rather than opening a broken position.

    `now` defaults to real wall-clock time (production) but is explicit
    so simulate.py can pass its own advancing simulated clock -- see
    check_and_close_positions' docstring for why this seam matters."""
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
        "symbol": symbol,
        "entry_price": market_price,
        "stop_loss_price": stop_loss_price,
        "take_profit_price": take_profit_price,
        "position_size_usd": round(VIRTUAL_CAPITAL_USD * proposal["max_position_size_pct"], 2),
        "status": "open",
        "opened_at": (now or datetime.now(UTC)).isoformat(),
    }


def _pnl(entry_price: float, exit_price: float, position_size_usd: float) -> tuple[float, float]:
    pnl_pct = (exit_price - entry_price) / entry_price
    return round(position_size_usd * pnl_pct, 2), round(pnl_pct, 4)


def check_and_close_positions(
    storage: Any, current_prices: dict[str, float], *, now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Check every open paper position against `current_prices` (mapping
    symbol -> current price); close and record any that hit stop-loss,
    take-profit, or MAX_HOLD_DAYS. Returns the list of positions closed
    this call (empty most cycles). A position whose symbol has no price
    this cycle (e.g. that source failed -- see observe.py) is left open
    and simply skipped, not treated as an error.

    `now` defaults to real wall-clock time (production) but is explicit
    so simulate.py can pass its own advancing simulated clock -- without
    it, MAX_HOLD_DAYS would never trigger in a fast simulation (simulated
    opened_at timestamps race ahead of real "now," so `now - opened_at`
    would compare against a `now` that barely moved during the run)."""
    now = now or datetime.now(UTC)
    closed: list[dict[str, Any]] = []
    for position in storage.open_paper_positions():
        current_price = current_prices.get(position.get("symbol", "BTCUSDT"))
        if current_price is None:
            continue
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
