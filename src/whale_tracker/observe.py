"""Gözlemci entry point: one pass over every source, store, print a report.
No trading logic. Run this manually or on a schedule (cron/Task Scheduler)
-- there is no built-in loop here yet, matching the Observer phase's own
"topla, sınıflandır, rapor et" scope (README.md)."""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

from whale_tracker.paper_trading import check_and_close_positions, open_position
from whale_tracker.report import render_report
from whale_tracker.signal import generate_candidates
from whale_tracker.sources.analysis import AnalysisError, generate_deep_analysis
from whale_tracker.sources.proposal import ProposalError, generate_final_proposal
from whale_tracker.sources.binance import BinanceMarketDataError, fetch_market_snapshot
from whale_tracker.sources.classify import classify_top_events
from whale_tracker.sources.news import NewsFeedError, fetch_headlines
from whale_tracker.sources.onchain import OnchainScanError, scan_new_transfers
from whale_tracker.sources.sentiment import FearGreedError, fetch_fear_greed
from whale_tracker.sources.technical import TechnicalDataError, fetch_technical_snapshot
from whale_tracker.storage import Storage

DEFAULT_DB_PATH = Path(__file__).resolve().parents[2] / "data" / "whale_tracker.db"
DEFAULT_CLASSIFY_LIMIT = 5

# Section 6: "Başlangıçta BTC ve ETH (likit, manipülasyonu daha zor)."
# Only market/technical data and signal generation are per-symbol -- the
# onchain stablecoin-flow scan and news feed stay shared (see signal.py's
# own docstring on this simplification).
TRACKED_SYMBOLS = ("BTCUSDT", "ETHUSDT")


def run_once(
    db_path: Path = DEFAULT_DB_PATH, *, min_usd: float = 1_000_000.0, classify_limit: int = DEFAULT_CLASSIFY_LIMIT,
) -> str:
    with Storage(db_path) as db:
        markets: dict[str, dict | None] = {}
        technicals: dict[str, dict | None] = {}
        for symbol in TRACKED_SYMBOLS:
            try:
                markets[symbol] = fetch_market_snapshot(symbol)
                db.insert_market_snapshot(markets[symbol])
            except BinanceMarketDataError as error:
                print(f"[uyarı] {symbol} Binance verisi alınamadı: {error}", file=sys.stderr)
                markets[symbol] = db.latest_market_snapshot(symbol)

            try:
                technicals[symbol] = fetch_technical_snapshot(symbol)
                db.insert_technical_snapshot(technicals[symbol])
            except TechnicalDataError as error:
                print(f"[uyarı] {symbol} teknik verisi alınamadı: {error}", file=sys.stderr)
                technicals[symbol] = db.latest_technical_snapshot(symbol)

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

        # Kademe 1: classify only the largest few events (cost/latency
        # bounded -- see sources/classify.py). A classification failure for
        # any one event is skipped, never fails the run.
        classifications = classify_top_events(onchain_events, limit=classify_limit) if onchain_events else {}
        classified_at = datetime.now(UTC).isoformat()
        for index, classification in classifications.items():
            event = onchain_events[index]
            db.insert_classification(event["tx_hash"], event["log_index"], classification, classified_at)
            event["classification"] = classification

        # Aşama 2, Sinyal üretici: corroborate the accumulated signals
        # (onchain flow, funding, sentiment, news, technical) into scored
        # candidates per tracked symbol. Still no trading -- see
        # signal.py's own docstring.
        all_candidates: list[dict] = []
        for symbol in TRACKED_SYMBOLS:
            candidates = generate_candidates(db, symbol=symbol)
            all_candidates.extend(candidates)
            for candidate in candidates:
                candidate_id = db.insert_signal_candidate(candidate)

                # Kademe 2: a candidate is exactly the "important situation"
                # PROJECT-PLAN.md means -- deep-analyze it, bounded to only
                # this rare case (see sources/analysis.py's cost note). A
                # failure here is skipped, same non-fatal contract as Kademe 1.
                try:
                    deep_context = {
                        "market_snapshot": markets[symbol],
                        "technical_snapshot": technicals[symbol],
                        "recent_headlines": new_headlines or db.recent_headlines(limit=5),
                    }
                    analysis = generate_deep_analysis(candidate, deep_context)
                    db.insert_deep_analysis(candidate_id, analysis, datetime.now(UTC).isoformat())
                    candidate["deep_analysis"] = analysis

                    # Kademe 3: only escalate to the rarest, most expensive
                    # tier when Kademe 2 itself already called this "strong"
                    # -- see sources/proposal.py's own docstring for the
                    # full gate (direction + stop-loss availability checked
                    # there too).
                    if analysis["corroboration_strength"] == "strong":
                        try:
                            proposal = generate_final_proposal(candidate, analysis, deep_context)
                            db.insert_final_proposal(candidate_id, proposal, datetime.now(UTC).isoformat())
                            candidate["final_proposal"] = proposal

                            # Aşama 3, Paper trading: a real proposal gets a
                            # simulated position, tracked against real prices
                            # from here on. No exchange client, no real
                            # money -- see paper_trading.py's own docstring.
                            if markets[symbol]:
                                position = open_position(
                                    candidate_id, proposal, markets[symbol]["mark_price"],
                                    deep_context["technical_snapshot"], symbol=symbol,
                                )
                                if position:
                                    db.insert_paper_position(position)
                                    candidate["paper_position"] = position
                        except ProposalError as error:
                            print(f"[uyarı] Kademe 3 öneri başarısız: {error}", file=sys.stderr)
                except AnalysisError as error:
                    print(f"[uyarı] Kademe 2 analiz başarısız: {error}", file=sys.stderr)

        # Every cycle, regardless of whether a new candidate showed up:
        # check already-open paper positions (any tracked symbol) against
        # this cycle's current prices.
        current_prices = {symbol: m["mark_price"] for symbol, m in markets.items() if m}
        closed_positions = check_and_close_positions(db, current_prices) if current_prices else []

        return render_report(
            onchain_events=onchain_events,
            market_snapshots=markets,
            sentiment_snapshot=sentiment,
            headlines=new_headlines,
            signal_candidates=all_candidates,
            closed_positions=closed_positions,
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
    parser.add_argument(
        "--classify-limit", type=int, default=DEFAULT_CLASSIFY_LIMIT,
        help="Kademe 1 sınıflandırmasını yalnızca en büyük N olaya uygula (maliyet/gecikme sınırlı). 0 = kapalı.",
    )
    args = parser.parse_args()
    report = run_once(args.db, min_usd=args.min_usd, classify_limit=args.classify_limit)
    print(report)
    if args.log_file:
        args.log_file.parent.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(UTC).isoformat()
        with args.log_file.open("a", encoding="utf-8") as handle:
            handle.write(f"\n----- {timestamp} -----\n{report}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
