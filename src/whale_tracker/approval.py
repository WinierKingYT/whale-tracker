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
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from whale_tracker.evaluation import evaluate_paper_trading
from whale_tracker.evidence import freshness_problems
from whale_tracker.paper_trading import compute_exit_levels, risk_guard_blocks_new_position
from whale_tracker.sizing import position_size_usd
from whale_tracker.sources.binance import BinanceMarketDataError, fetch_market_snapshot
from whale_tracker.sources.technical import TechnicalDataError, fetch_technical_snapshot
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

# A pending request is a statement about the market at created_at. After
# this long it is no longer a statement about now -- it expires instead
# of waiting indefinitely for a human.
APPROVAL_TTL = timedelta(minutes=60)

# At approval time the live price may have moved from the proposal's
# entry. Beyond this drift the stop/target geometry and the risk sizing
# were computed for a different trade -- the request is invalidated, not
# approved (e.g. proposed at $70,000, approved at $73,000).
MAX_APPROVAL_PRICE_DRIFT = 0.005  # 0.5%


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
    now = now or datetime.now(UTC)
    if approval_blockers(storage, symbol, market_price, now=now):
        return None
    exits = compute_exit_levels(proposal, market_price, technical)
    if exits is None:
        return None
    stop_loss_price, take_profit_price = exits
    # Same sizing function as paper_trading.open_position -- never a copy.
    size_usd = position_size_usd(ASAMA5_CAPITAL_USD, market_price, stop_loss_price,
                                 risk_pct=proposal["max_position_size_pct"])
    if size_usd is None:
        return None

    request = {
        "signal_candidate_id": candidate_id,
        "symbol": symbol,
        "entry_price": market_price,
        "stop_loss_price": stop_loss_price,
        "take_profit_price": take_profit_price,
        "position_size_usd": size_usd,
        "status": "pending",
        "created_at": now.isoformat(),
        "expires_at": (now + APPROVAL_TTL).isoformat(),
    }
    request["id"] = storage.insert_approval_request(request)
    return request


def _is_expired(request: dict[str, Any], now: datetime) -> bool:
    # Rows created before expires_at existed have none: treat as expired
    # (fail-closed) rather than valid forever.
    if not request.get("expires_at"):
        return True
    return now >= datetime.fromisoformat(request["expires_at"])


def expire_stale_requests(storage: Any, *, now: datetime | None = None) -> list[int]:
    """Mark every pending request past its expiry as 'expired'."""
    now = now or datetime.now(UTC)
    expired = []
    for request in storage.pending_approval_requests():
        if _is_expired(request, now):
            storage.decide_approval_request(request["id"], status="expired", decided_at=now.isoformat(),
                                            note="süresi doldu")
            expired.append(request["id"])
    return expired


def approval_time_blockers(
    storage: Any, request: dict[str, Any], current_price: float, *, now: datetime | None = None,
) -> list[str]:
    """Re-validate a pending request at the moment a human approves it:
    expiry, live price drift from the proposed entry, the stop/target
    geometry against the live price, and every creation-time gate
    (flag, readiness, freshness, Risk Guard) again."""
    now = now or datetime.now(UTC)
    blockers: list[str] = []
    if request["status"] != "pending":
        return [f"istek zaten '{request['status']}'"]
    if _is_expired(request, now):
        blockers.append("süresi doldu")
    drift = abs(current_price - request["entry_price"]) / request["entry_price"]
    if drift > MAX_APPROVAL_PRICE_DRIFT:
        blockers.append(
            f"fiyat kaydı {drift:.2%} > {MAX_APPROVAL_PRICE_DRIFT:.1%} "
            f"(öneri ${request['entry_price']:,.2f}, şimdi ${current_price:,.2f})"
        )
    if not (request["stop_loss_price"] < current_price < request["take_profit_price"]):
        blockers.append("güncel fiyat stop/hedef aralığının dışında")
    blockers.extend(approval_blockers(storage, request["symbol"], current_price, now=now))
    return blockers


def approve_request(
    storage: Any, request_id: int, current_price: float, *, now: datetime | None = None, note: str | None = None,
) -> tuple[str, list[str]]:
    """The only path to 'approved'. Returns (resulting_status, reasons).
    Anything that fails re-validation ends the request -- 'expired' or
    'invalidated' -- instead of leaving a stale proposal approvable later."""
    now = now or datetime.now(UTC)
    request = storage.get_approval_request(request_id)
    if request is None:
        return "not_found", ["istek bulunamadı"]
    blockers = approval_time_blockers(storage, request, current_price, now=now)
    if request["status"] != "pending":
        return request["status"], blockers
    if blockers:
        status = "expired" if blockers == ["süresi doldu"] else "invalidated"
        storage.decide_approval_request(request_id, status=status, decided_at=now.isoformat(), note="; ".join(blockers))
        return status, blockers
    storage.decide_approval_request(request_id, status="approved", decided_at=now.isoformat(), note=note)
    return "approved", []


def _render_request(request: dict[str, Any]) -> str:
    return (
        f"#{request['id']} [{request['status']}] {request['symbol']} "
        f"giriş=${request['entry_price']:,.2f} stop=${request['stop_loss_price']:,.2f} "
        f"hedef=${request['take_profit_price']:,.2f} boyut=${request['position_size_usd']:,.2f} "
        f"oluşturulma={request['created_at']} son={request.get('expires_at') or '-'}"
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
        expire_stale_requests(db)
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

        if args.command == "reject":
            db.decide_approval_request(args.request_id, status="rejected", decided_at=datetime.now(UTC).isoformat(),
                                       note=args.note)
            print(f"#{args.request_id} -> rejected")
            return 0

        # Approval re-validates against the market NOW, not the market at
        # proposal time: fetch live evidence first. No live price -> no
        # approval (the request stays pending until it expires).
        try:
            market = fetch_market_snapshot(request["symbol"])
            db.insert_market_snapshot(market)
            db.insert_technical_snapshot(fetch_technical_snapshot(request["symbol"]))
        except (BinanceMarketDataError, TechnicalDataError) as error:
            print(f"Canlı veri alınamadı, onay verilmedi (istek beklemede kaldı): {error}")
            return 1
        status, reasons = approve_request(db, args.request_id, market["mark_price"], note=args.note)
        print(f"#{args.request_id} -> {status}")
        for reason in reasons:
            print(f"  - {reason}")
        if status == "approved":
            print(
                "Not: bu yalnızca bir karar kaydıdır, hiçbir işlem yürütülmedi -- "
                "gerçek işlem kendi ayrı, onaylı bot/script'in tarafından, kendi API anahtarınla yapılmalı."
            )
            return 0
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
