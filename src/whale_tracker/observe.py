"""Gözlemci entry point: one pass over every source, store, print a report.
No trading logic. Run this manually or on a schedule (cron/Task Scheduler)
-- there is no built-in loop here yet, matching the Observer phase's own
"topla, sınıflandır, rapor et" scope (README.md)."""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

from whale_tracker.report import render_report
from whale_tracker.sources.binance import BinanceMarketDataError, fetch_market_snapshot
from whale_tracker.sources.news import NewsFeedError, fetch_headlines
from whale_tracker.sources.onchain import OnchainScanError, scan_new_transfers
from whale_tracker.sources.sentiment import FearGreedError, fetch_fear_greed
from whale_tracker.storage import Storage

DEFAULT_DB_PATH = Path(__file__).resolve().parents[2] / "data" / "whale_tracker.db"


def run_once(db_path: Path = DEFAULT_DB_PATH, *, min_usd: float = 1_000_000.0) -> str:
    with Storage(db_path) as db:
        try:
            market = fetch_market_snapshot("BTCUSDT")
            db.insert_market_snapshot(market)
        except BinanceMarketDataError as error:
            print(f"[uyarı] Binance verisi alınamadı: {error}", file=sys.stderr)
            market = db.latest_market_snapshot("BTCUSDT")

        try:
            sentiment = fetch_fear_greed()
            db.insert_sentiment_snapshot(sentiment)
        except FearGreedError as error:
            print(f"[uyarı] Fear & Greed verisi alınamadı: {error}", file=sys.stderr)
            sentiment = db.latest_sentiment_snapshot("fear_greed")

        try:
            onchain_events = scan_new_transfers(db, min_usd=min_usd)
        except OnchainScanError as error:
            print(f"[uyarı] Zincir üstü tarama başarısız: {error}", file=sys.stderr)
            onchain_events = []

        try:
            new_headlines = [h for h in fetch_headlines() if db.insert_headline(h)]
        except NewsFeedError as error:
            print(f"[uyarı] Haber akışı alınamadı: {error}", file=sys.stderr)
            new_headlines = []

        return render_report(
            onchain_events=onchain_events,
            market_snapshot=market,
            sentiment_snapshot=sentiment,
            headlines=new_headlines,
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="whale-tracker Gözlemci -- tek geçiş")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--min-usd", type=float, default=1_000_000.0)
    parser.add_argument(
        "--log-file", type=Path, default=None,
        help="Append the report here (with a timestamp header) instead of only printing it. "
             "Needed for scheduled runs (Task Scheduler/cron), where stdout is otherwise lost.",
    )
    args = parser.parse_args()
    report = run_once(args.db, min_usd=args.min_usd)
    print(report)
    if args.log_file:
        args.log_file.parent.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(UTC).isoformat()
        with args.log_file.open("a", encoding="utf-8") as handle:
            handle.write(f"\n----- {timestamp} -----\n{report}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
