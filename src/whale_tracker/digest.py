"""Daily digest + instant alerts, delivered through notify.py.

- Daily digest: once per local day, on the first observer cycle at or
  after `daily_digest_hour` (default 09:00). "Sent today" is remembered in
  the scan_cursor table under DIGEST_CURSOR as YYYYMMDD, and only marked
  after a successful send, so a failed send retries next cycle.
- Instant alerts: the rare events worth interrupting for -- a Kademe 3
  proposal, a paper position opening or closing. The plan's own wording
  is "günlük/anlık rapor gönderir".

Read-only SQL against the observer's own tables, same convention as
status.py. Every message is paper-trading bookkeeping: nothing here
places or suggests placing a real order (README "Kritik sınır")."""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from whale_tracker.notify import NotifyError, load_config, send
from whale_tracker.signal import _aggregate_exchange_flow
from whale_tracker.sources.classify import kademe1_circuit_open
from whale_tracker.storage import Storage

# Not imported from observe.py: observe imports this module.
DEFAULT_DB_PATH = Path(__file__).resolve().parents[2] / "data" / "whale_tracker.db"
DIGEST_CURSOR = "daily_digest"
# Observer runs every 15 minutes; no fresh market data for 45 minutes
# means at least two cycles were missed.
STALE_AFTER = timedelta(minutes=45)


def _rows(db: Storage, query: str, params: tuple = ()) -> list[Any]:
    return db._conn.execute(query, params).fetchall()


def _pct_change(db: Storage, symbol: str, since: str) -> tuple[float | None, float | None]:
    latest = db.latest_market_snapshot(symbol)
    earlier = db.market_snapshot_near(symbol, since)
    if not latest:
        return None, None
    if not earlier or not earlier["mark_price"]:
        return latest["mark_price"], None
    return latest["mark_price"], (latest["mark_price"] - earlier["mark_price"]) / earlier["mark_price"]


def _usd_millions(value: float) -> str:
    return f"${abs(value) / 1_000_000:,.1f}M"


def compose_digest(db: Storage, *, now: datetime | None = None) -> str:
    now = now or datetime.now(UTC)
    since = (now - timedelta(hours=24)).isoformat()
    lines: list[str] = []

    market_parts = []
    for (symbol,) in _rows(db, "SELECT DISTINCT symbol FROM market_snapshots ORDER BY symbol"):
        price, change = _pct_change(db, symbol, since)
        if price is None:
            continue
        change_text = f" ({change:+.1%})" if change is not None else ""
        market_parts.append(f"{symbol.removesuffix('USDT')} ${price:,.0f}{change_text}")
    lines.append("Piyasa (24s): " + (", ".join(market_parts) or "veri yok"))

    sentiment = db.latest_sentiment_snapshot("fear_greed")
    if sentiment:
        lines.append(f"Fear&Greed: {sentiment['value']:.0f} ({sentiment['label']})")

    transfers = _rows(db, "SELECT COUNT(*) FROM onchain_events WHERE observed_at >= ?", (since,))[0][0]
    flow = _aggregate_exchange_flow(db, hours=24, now=now)
    direction = "giriş" if flow["net_inflow_usd"] >= 0 else "çıkış"
    lines.append(f"Zincir üstü: {transfers} büyük transfer, borsalara net {direction} {_usd_millions(flow['net_inflow_usd'])}")

    by_direction = dict(_rows(db, "SELECT direction, COUNT(*) FROM signal_candidates WHERE generated_at >= ? GROUP BY direction", (since,)))
    by_strength = dict(_rows(db, "SELECT corroboration_strength, COUNT(*) FROM deep_analyses WHERE generated_at >= ? GROUP BY corroboration_strength", (since,)))
    proposals = _rows(db, "SELECT COUNT(*) FROM final_proposals WHERE generated_at >= ?", (since,))[0][0]
    lines.append(
        f"Adaylar: birikim {by_direction.get('accumulation', 0)}, dağıtım {by_direction.get('distribution', 0)}; "
        f"Kademe 2: {sum(by_strength.values())} (strong {by_strength.get('strong', 0)}); Kademe 3: {proposals}"
    )

    open_count = _rows(db, "SELECT COUNT(*) FROM paper_positions WHERE status = 'open'")[0][0]
    opened = _rows(db, "SELECT COUNT(*) FROM paper_positions WHERE opened_at >= ?", (since,))[0][0]
    closed = _rows(db, "SELECT COUNT(*), COALESCE(SUM(pnl_usd), 0) FROM paper_positions WHERE closed_at >= ?", (since,))[0]
    lines.append(f"Kağıt pozisyon: açık {open_count}, 24s'te açılan {opened}, kapanan {closed[0]} (P&L ${closed[1]:+,.2f})")

    ai_parts = [
        f"{call_type.split('_')[0].replace('kademe', 'K')}: {succeeded}/{attempted}"
        for call_type, attempted, succeeded in _rows(
            db, "SELECT call_type, SUM(attempted), SUM(succeeded) FROM ai_call_log WHERE called_at >= ? GROUP BY call_type ORDER BY call_type", (since,),
        )
    ]
    breaker = " [K1 devre kesici AÇIK]" if kademe1_circuit_open(db, now=now) else ""
    lines.append("AI çağrıları: " + (", ".join(ai_parts) or "yok") + breaker)

    latest = _rows(db, "SELECT MAX(observed_at) FROM market_snapshots")[0][0]
    if latest is None:
        lines.append("[UYARI] Hiç piyasa verisi yok -- gözlemci hiç çalışmamış olabilir.")
    else:
        age = now - datetime.fromisoformat(latest)
        minutes = int(age.total_seconds() // 60)
        if age > STALE_AFTER:
            lines.append(f"[UYARI] Son veri {minutes} dk önce -- gözlemci durmuş olabilir.")
        else:
            lines.append(f"Gözlemci sağlıklı: son veri {minutes} dk önce.")
    return "\n".join(lines)


def digest_due(db: Storage, *, local_now: datetime, digest_hour: int) -> bool:
    today = int(local_now.strftime("%Y%m%d"))
    return local_now.hour >= digest_hour and db.get_scan_cursor(DIGEST_CURSOR) != today


def cycle_alerts(candidates: list[dict[str, Any]], closed_positions: list[dict[str, Any]]) -> list[tuple[str, str]]:
    """(title, message) for every alert-worthy event from one observer cycle."""
    alerts: list[tuple[str, str]] = []
    for candidate in candidates:
        proposal = candidate.get("final_proposal")
        if proposal and proposal.get("action") == "long_candidate":
            alerts.append((
                f"Kademe 3 önerisi: {candidate['symbol']}",
                (f"long_candidate, stop ${proposal['stop_loss_price']:,.2f}, "
                 f"güven {candidate['confidence']:.2f}, kanaat {proposal.get('conviction', '?')}. "
                 "KAĞIT işlem -- gerçek emir yok."),
            ))
        position = candidate.get("paper_position")
        if position:
            alerts.append((
                f"Kağıt pozisyon açıldı: {position['symbol']}",
                (f"giriş ${position['entry_price']:,.2f}, stop ${position['stop_loss_price']:,.2f}, "
                 f"hedef ${position['take_profit_price']:,.2f}, boyut ${position['position_size_usd']:,.2f}"),
            ))
    for position in closed_positions:
        alerts.append((
            f"Kağıt pozisyon kapandı: {position.get('symbol', 'BTCUSDT')}",
            f"{position['status']}, çıkış ${position['exit_price']:,.2f}, P&L {position['pnl_pct']:+.2%} (${position['pnl_usd']:+,.2f})",
        ))
    return alerts


def notify_after_cycle(
    db: Storage, *, candidates: list[dict[str, Any]], closed_positions: list[dict[str, Any]],
    now: datetime | None = None, local_now: datetime | None = None, config: dict[str, Any] | None = None,
) -> None:
    """Called once at the end of every observer cycle. Never raises -- a
    notification problem is logged and the cycle carries on."""
    config = load_config() if config is None else config
    if not config:
        return
    now = now or datetime.now(UTC)
    local_now = local_now or datetime.now().astimezone()
    try:
        for title, message in cycle_alerts(candidates, closed_positions):
            send(config, title, message, priority=4, tags=["chart_with_upwards_trend"])
        if digest_due(db, local_now=local_now, digest_hour=config["daily_digest_hour"]):
            send(config, f"whale-tracker günlük özet -- {local_now:%d.%m %H:%M}", compose_digest(db, now=now))
            db.set_scan_cursor(DIGEST_CURSOR, int(local_now.strftime("%Y%m%d")), now.isoformat())
    except NotifyError as error:
        print(f"[uyarı] bildirim gönderilemedi: {error}", file=sys.stderr)


def main() -> int:
    parser = argparse.ArgumentParser(description="whale-tracker günlük özet")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--send", action="store_true", help="Özeti şimdi gönder (günlük sayaca dokunmaz)")
    args = parser.parse_args()
    with Storage(args.db) as db:
        text = compose_digest(db)
    print(text)
    if args.send:
        config = load_config()
        if not config:
            print("Bildirim yapılandırılmamış -- önce: python -m whale_tracker.notify --init")
            return 1
        send(config, f"whale-tracker özet -- {datetime.now().astimezone():%d.%m %H:%M}", text)
        print("\nGönderildi.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
