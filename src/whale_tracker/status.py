"""Tek-komutla durum özeti -- kaç aday, kaç Kademe 2/3'e ulaştı, açık
pozisyon var mı, en son ne zaman veri geldi. Gerçek veritabanı için de
(data/whale_tracker.db) simülasyon/kalibrasyon veritabanları için de
çalışır -- --db ile hangisine bakılacağı seçilir.

Salt okunur, hiçbir şeyi değiştirmez. DB'nin kendi tablolarına doğrudan
SQL ile bakar (Storage'a bu tek-seferlik özet sorguları için yeni
metodlar eklemek yerine) -- bu modülün kendi görevi, storage.py'nin genel
amaçlı arayüzünü şişirmeden."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from whale_tracker.storage import Storage

DEFAULT_DB_PATH = Path(__file__).resolve().parents[2] / "data" / "whale_tracker.db"


def _count(db: Storage, query: str, params: tuple = ()) -> int:
    row = db._conn.execute(query, params).fetchone()
    return int(row[0]) if row else 0


def _group_counts(db: Storage, table: str, column: str) -> dict[str, int]:
    rows = db._conn.execute(f"SELECT {column}, COUNT(*) c FROM {table} GROUP BY {column}").fetchall()
    return {str(row[column]): row["c"] for row in rows}


def compute_status(db: Storage) -> dict[str, Any]:
    """Read-only snapshot of everything in `db` right now."""
    market_range = db._conn.execute(
        "SELECT MIN(observed_at) start, MAX(observed_at) end FROM market_snapshots"
    ).fetchone()

    return {
        "market_snapshots": {
            "total": _count(db, "SELECT COUNT(*) FROM market_snapshots"),
            "by_symbol": _group_counts(db, "market_snapshots", "symbol"),
            "earliest": market_range["start"] if market_range else None,
            "latest": market_range["end"] if market_range else None,
            "latest_prices": {
                symbol: (db.latest_market_snapshot(symbol) or {}).get("mark_price")
                for symbol in _group_counts(db, "market_snapshots", "symbol")
            },
        },
        "onchain_events": {
            "total": _count(db, "SELECT COUNT(*) FROM onchain_events"),
            "classified": _count(db, "SELECT COUNT(*) FROM event_classifications"),
        },
        "headlines": {"total": _count(db, "SELECT COUNT(*) FROM headlines")},
        "signal_candidates": {
            "total": _count(db, "SELECT COUNT(*) FROM signal_candidates"),
            "by_symbol": _group_counts(db, "signal_candidates", "symbol"),
            "by_direction": _group_counts(db, "signal_candidates", "direction"),
        },
        "deep_analyses": {
            "total": _count(db, "SELECT COUNT(*) FROM deep_analyses"),
            "by_strength": _group_counts(db, "deep_analyses", "corroboration_strength"),
        },
        "final_proposals": {
            "total": _count(db, "SELECT COUNT(*) FROM final_proposals"),
            "by_action": _group_counts(db, "final_proposals", "action"),
        },
        "paper_positions": {
            "open": _count(db, "SELECT COUNT(*) FROM paper_positions WHERE status = 'open'"),
            "closed": _count(db, "SELECT COUNT(*) FROM paper_positions WHERE status != 'open'"),
            "by_status": _group_counts(db, "paper_positions", "status"),
        },
        "ai_calls": db.ai_call_log_summary(),
    }


def render_status(status: dict[str, Any], *, db_path: Path) -> str:
    lines = [f"=== whale-tracker durum özeti ({db_path}) ===", ""]

    market = status["market_snapshots"]
    lines.append(f"Piyasa verisi: {market['total']} kayıt, {market['earliest']} -- {market['latest']}")
    for symbol, price in market["latest_prices"].items():
        count = market["by_symbol"].get(symbol, 0)
        price_text = f"${price:,.2f}" if price is not None else "?"
        lines.append(f"  {symbol}: {count} kayıt, son fiyat {price_text}")

    onchain = status["onchain_events"]
    lines.append(f"\nZincir üstü olay: {onchain['total']} (Kademe 1 sınıflandırılan: {onchain['classified']})")
    lines.append(f"Haberler: {status['headlines']['total']}")

    candidates = status["signal_candidates"]
    lines.append(f"\nSinyal adayı: {candidates['total']} toplam")
    if candidates["by_symbol"]:
        lines.append(f"  sembol: {candidates['by_symbol']}")
    if candidates["by_direction"]:
        lines.append(f"  yön: {candidates['by_direction']}")

    analyses = status["deep_analyses"]
    lines.append(f"\nKademe 2 (derin analiz): {analyses['total']} toplam")
    if analyses["by_strength"]:
        lines.append(f"  güç: {analyses['by_strength']}")

    proposals = status["final_proposals"]
    lines.append(f"\nKademe 3 (öneri): {proposals['total']} toplam")
    if proposals["by_action"]:
        lines.append(f"  aksiyon: {proposals['by_action']}")

    positions = status["paper_positions"]
    lines.append(f"\nKağıt pozisyon: açık={positions['open']}, kapanmış={positions['closed']}")
    if positions["by_status"]:
        lines.append(f"  durum: {positions['by_status']}")

    ai_calls = status["ai_calls"]
    if ai_calls:
        lines.append("\nAI çağrıları (kota kullanımı):")
        for row in ai_calls:
            rate = row["succeeded"] / row["attempted"] if row["attempted"] else 0.0
            avg_s = row["avg_duration_ms"] / 1000 if row["avg_duration_ms"] else 0.0
            warning = f", {row['failed_cycles']} döngü sıfır başarı" if row["failed_cycles"] else ""
            lines.append(
                f"  {row['call_type']}: {row['cycles']} döngü, {row['succeeded']}/{row['attempted']} başarılı "
                f"(%{rate*100:.0f}), ort. {avg_s:.1f}s{warning}"
            )

    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="whale-tracker -- tek komutla durum özeti")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    args = parser.parse_args()
    with Storage(args.db) as db:
        status = compute_status(db)
    print(render_status(status, db_path=args.db))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
