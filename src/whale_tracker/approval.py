"""Asama 5 skeleton: Yari otomatik (onayli) -- see docs/PROJECT-PLAN.md
section 8, "Kucuk gercek parayla; her islemi kullanici onaylar."

Kritik sinir (README.md, "Kritik sinir"): this module NEVER executes a
trade, at any stage, even with approval. It only records that the system
proposed one and whether a human decided to approve or reject it.
"Approved" means "the user's own separate, already-approved bot/script
may now act on this" -- not "the trade happened." No exchange client, no
API key, no order-placing call exists anywhere in this codebase; that
boundary is categorical, not something a flag here lifts.

Two independent gates, both required (see asama5_active):
1. ASAMA5_ENABLED -- a deliberate, reviewed code change (a git commit),
   same posture as this machine's Brain-Eleven shadow-accept pattern:
   real-money behavior is opt-in and off by default, never silently
   turned on by data alone.
2. evaluation.ready_for_asama5 -- the plan's own statistical bar
   (enough closed paper positions, beats BTC-hold) plus entries beating
   random-time entries (evaluation.ASAMA5_EDGE_P_VALUE). This is a
   measurement, not a decision (see evaluation.py's own docstring on
   render_evaluation_report's [HAZIR] line) -- meeting it does not
   flip ASAMA5_ENABLED for you.

Even when both gates hold, create_approval_request only ever produces a
'pending' row -- and it re-checks every gate itself (approval_blockers):
ASAMA5_ENABLED, ready_for_asama5, evidence freshness, the caller's price
against the stored snapshot, and Risk Guard. The financial boundary never
depends on the caller having checked first. A human runs `python -m whale_tracker.approval list` /
`approve <id>` / `reject <id>` -- there is no other path to 'approved'."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from whale_tracker.evaluation import evaluate_paper_trading
from whale_tracker.evidence import freshness_problems
from whale_tracker.paper_trading import compute_exit_levels, risk_guard_blocks_new_position
from whale_tracker.storage import Storage

DEFAULT_DB_PATH = Path(__file__).resolve().parents[2] / "data" / "whale_tracker.db"

# Off by default -- flipping this is a deliberate code change, not
# something data (e.g. ready_for_asama5 becoming True) does on its own.
# See module docstring.
ASAMA5_ENABLED = False

# Real capital for Aşama 5 sizing, distinct from paper_trading's
# VIRTUAL_CAPITAL_USD -- must be set to an actual amount the user has
# decided to risk before this phase means anything. Left at 0 so a
# misconfiguration (ASAMA5_ENABLED flipped without ever setting this)
# fails safe: create_approval_request refuses to size a request against
# zero capital rather than silently producing a $0 proposal.
ASAMA5_CAPITAL_USD = 0.0

# The price a caller hands create_approval_request must agree with the
# stored, fresh market snapshot -- a request priced off anything else
# (an old variable, a different symbol) is refused, not recorded.
MAX_ENTRY_PRICE_DEVIATION = 0.005  # 0.5%


def asama5_active(storage: Any) -> bool:
    """True only when both gates hold -- see module docstring. Checked
    fresh every call (not cached) since evaluate_paper_trading reflects
    whatever has closed so far; a strategy that stops beating BTC-hold
    after a bad stretch should stop qualifying immediately, not keep
    riding on a stale evaluation from when it did."""
    if not ASAMA5_ENABLED:
        return False
    scorecard = evaluate_paper_trading(storage)
    return bool(scorecard.get("ready_for_asama5"))


def approval_blockers(
    storage: Any, symbol: str, market_price: float, *, now: datetime | None = None,
) -> list[str]:
    """Every reason an Aşama 5 approval must NOT be created right now;
    empty list means all gates hold. Order: cheapest/most fundamental
    first, but all are evaluated so the log shows the full picture."""
    now = now or datetime.now(UTC)
    blockers: list[str] = []
    if not ASAMA5_ENABLED:
        blockers.append("ASAMA5_ENABLED kapalı")
    elif not asama5_active(storage):
        blockers.append("ready_for_asama5 sağlanmıyor")
    if ASAMA5_CAPITAL_USD <= 0:
        blockers.append("ASAMA5_CAPITAL_USD ayarlanmamış")
    blockers.extend(freshness_problems(storage, symbol, now=now))
    market = storage.latest_market_snapshot(symbol)
    if market and market.get("mark_price"):
        deviation = abs(market_price - market["mark_price"]) / market["mark_price"]
        if deviation > MAX_ENTRY_PRICE_DEVIATION:
            blockers.append(
                f"giriş fiyatı saklı snapshot'tan sapıyor ({deviation:.2%} > {MAX_ENTRY_PRICE_DEVIATION:.1%})"
            )
    risk_block = risk_guard_blocks_new_position(storage, now=now)
    if risk_block:
        blockers.append(f"Risk Guard: {risk_block}")
    return blockers


def create_approval_request(
    storage: Any, candidate_id: int, proposal: dict[str, Any], market_price: float,
    technical: dict[str, Any] | None, *, symbol: str = "BTCUSDT", now: datetime | None = None,
) -> dict[str, Any] | None:
    """Build and store a pending approval request from a Kademe 3
    long_candidate proposal. Returns None (creates nothing) when the
    risk/reward setup doesn't make sense (see compute_exit_levels) or
    ASAMA5_CAPITAL_USD isn't configured -- same "don't record a broken
    proposal" posture as paper_trading.open_position, which this
    deliberately mirrors so a real-money request is judged identically
    to its paper counterpart, never a looser or stricter copy.

    Also returns None when any approval_blockers() gate fails -- checked
    here, not only by the caller, so a direct call can't bypass them."""
    if approval_blockers(storage, symbol, market_price, now=now):
        return None
    exits = compute_exit_levels(proposal, market_price, technical)
    if exits is None:
        return None
    stop_loss_price, take_profit_price = exits

    request = {
        "signal_candidate_id": candidate_id,
        "symbol": symbol,
        "entry_price": market_price,
        "stop_loss_price": stop_loss_price,
        "take_profit_price": take_profit_price,
        "position_size_usd": round(ASAMA5_CAPITAL_USD * proposal["max_position_size_pct"], 2),
        "status": "pending",
        "created_at": (now or datetime.now(UTC)).isoformat(),
    }
    request["id"] = storage.insert_approval_request(request)
    return request


def _render_request(request: dict[str, Any]) -> str:
    return (
        f"#{request['id']} [{request['status']}] {request['symbol']} "
        f"giriş=${request['entry_price']:,.2f} stop=${request['stop_loss_price']:,.2f} "
        f"hedef=${request['take_profit_price']:,.2f} boyut=${request['position_size_usd']:,.2f} "
        f"oluşturulma={request['created_at']}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="whale-tracker Aşama 5 -- bekleyen gerçek-para önerilerini listele/onayla/reddet. "
                     "Hiçbir komut işlem YÜRÜTMEZ -- yalnızca bu veritabanına bir karar kaydeder.",
    )
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("list", help="Bekleyen onay isteklerini listele")

    approve_parser = subparsers.add_parser("approve", help="Bir isteği onayla")
    approve_parser.add_argument("request_id", type=int)
    approve_parser.add_argument("--note", default=None)

    reject_parser = subparsers.add_parser("reject", help="Bir isteği reddet")
    reject_parser.add_argument("request_id", type=int)
    reject_parser.add_argument("--note", default=None)

    args = parser.parse_args()
    with Storage(args.db) as db:
        if args.command == "list":
            pending = db.pending_approval_requests()
            if not pending:
                print("Bekleyen onay isteği yok.")
                return 0
            for request in pending:
                print(_render_request(request))
            return 0

        request = db.get_approval_request(args.request_id)
        if request is None:
            print(f"İstek bulunamadı: #{args.request_id}")
            return 1
        if request["status"] != "pending":
            print(f"İstek zaten karara bağlanmış: {_render_request(request)}")
            return 1

        status = "approved" if args.command == "approve" else "rejected"
        db.decide_approval_request(args.request_id, status=status, decided_at=datetime.now(UTC).isoformat(), note=args.note)
        print(f"#{args.request_id} -> {status}")
        if status == "approved":
            print(
                "Not: bu yalnızca bir karar kaydıdır, hiçbir işlem yürütülmedi -- "
                "gerçek işlem kendi ayrı, onaylı bot/script'in tarafından, kendi API anahtarınla yapılmalı."
            )
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
