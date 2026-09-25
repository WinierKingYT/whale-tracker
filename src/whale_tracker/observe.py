"""Gözlemci entry point: one pass over every source, store, print a report.
No trading logic. Run this manually or on a schedule (cron/Task Scheduler)
-- there is no built-in loop here yet, matching the Observer phase's own
"topla, sınıflandır, rapor et" scope (README.md)."""

from __future__ import annotations

import argparse
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from whale_tracker.approval import asama5_active, create_approval_request, expire_stale_requests
from whale_tracker.digest import notify_after_cycle
from whale_tracker.evidence import ABSTAIN, freshness_problems
from whale_tracker.paper_trading import (
    available_notional_usd,
    check_and_close_positions,
    open_position,
    risk_guard_blocks_new_position,
)
from whale_tracker.report import render_report
from whale_tracker.signal import generate_candidates
from whale_tracker.sources.analysis import AnalysisError, generate_deep_analysis
from whale_tracker.sources.binance import BinanceMarketDataError, fetch_market_snapshot
from whale_tracker.sources.classify import (
    CIRCUIT_BREAKER_COOLDOWN_MINUTES,
    CIRCUIT_BREAKER_FAILURE_THRESHOLD,
    classify_top_events,
    kademe1_circuit_open,
)
from whale_tracker.sources.news import NewsFeedError, fetch_headlines
from whale_tracker.sources.onchain import OnchainScanError, scan_new_transfers
from whale_tracker.sources.proposal import ProposalError, generate_final_proposal
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
        # Per-symbol reasons this cycle must ABSTAIN (evidence.py). The DB
        # fallback below is kept for position monitoring and the report --
        # never as evidence for a new decision.
        abstain_reasons: dict[str, list[str]] = {symbol: [] for symbol in TRACKED_SYMBOLS}
        for symbol in TRACKED_SYMBOLS:
            try:
                markets[symbol] = fetch_market_snapshot(symbol)
                db.insert_market_snapshot(markets[symbol])
            except BinanceMarketDataError as error:
                print(f"[uyarı] {symbol} Binance verisi alınamadı: {error}", file=sys.stderr)
                markets[symbol] = db.latest_market_snapshot(symbol)
                abstain_reasons[symbol].append("market verisi bu döngüde alınamadı")

            try:
                technicals[symbol] = fetch_technical_snapshot(symbol)
                db.insert_technical_snapshot(technicals[symbol])
            except TechnicalDataError as error:
                print(f"[uyarı] {symbol} teknik verisi alınamadı: {error}", file=sys.stderr)
                technicals[symbol] = db.latest_technical_snapshot(symbol)
                abstain_reasons[symbol].append("technical verisi bu döngüde alınamadı")

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
            # A failed scan leaves the flow window silently incomplete.
            for reasons in abstain_reasons.values():
                reasons.append("zincir üstü tarama bu döngüde başarısız")

        try:
            new_headlines = [h for h in fetch_headlines() if db.insert_headline(h)]
        except NewsFeedError as error:
            print(f"[uyarı] Haber akışı alınamadı: {error}", file=sys.stderr)
            new_headlines = []

        # Kademe 1: classify only the largest few events (cost/latency
        # bounded -- see sources/classify.py). A classification failure for
        # any one event is skipped, never fails the run. The circuit
        # breaker skips the call entirely (not logged -- see its own
        # docstring) once it's been failing consistently, rather than
        # paying the timeout cost every single cycle for a call almost
        # certain to fail.
        classifications: dict[int, dict] = {}
        if onchain_events and kademe1_circuit_open(db):
            print(
                f"[uyarı] Kademe 1 (Hermes) devre kesici açık: son {CIRCUIT_BREAKER_FAILURE_THRESHOLD} deneme "
                f"başarısız, {CIRCUIT_BREAKER_COOLDOWN_MINUTES} dk soğuma sürüyor -- bu döngü atlanıyor",
                file=sys.stderr,
            )
        elif onchain_events:
            kademe1_attempted = min(classify_limit, len(onchain_events))
            kademe1_started = time.perf_counter()
            classifications = classify_top_events(onchain_events, limit=classify_limit)
            classified_at = datetime.now(UTC).isoformat()
            for index, classification in classifications.items():
                event = onchain_events[index]
                db.insert_classification(event["tx_hash"], event["log_index"], classification, classified_at)
                event["classification"] = classification
            if kademe1_attempted:
                kademe1_succeeded = len(classifications)
                db.insert_ai_call_log(
                    "kademe1_hermes", attempted=kademe1_attempted, succeeded=kademe1_succeeded,
                    duration_ms=(time.perf_counter() - kademe1_started) * 1000,
                    error_reason=None if kademe1_succeeded == kademe1_attempted else "bir veya daha fazla çağrı başarısız",
                    called_at=classified_at,
                )

        # Aşama 2, Sinyal üretici: corroborate the accumulated signals
        # (onchain flow, funding, sentiment, news, technical) into scored
        # candidates per tracked symbol. Still no trading -- see
        # signal.py's own docstring.
        all_candidates: list[dict] = []
        for symbol in TRACKED_SYMBOLS:
            abstain_reasons[symbol].extend(freshness_problems(db, symbol))
            if abstain_reasons[symbol]:
                print(f"[{ABSTAIN}] {symbol}: {'; '.join(abstain_reasons[symbol])}", file=sys.stderr)
                continue
            candidates = generate_candidates(db, symbol=symbol)
            all_candidates.extend(candidates)
            for candidate in candidates:
                candidate_id = db.insert_signal_candidate(candidate)

                # Kademe 2: a candidate is exactly the "important situation"
                # PROJECT-PLAN.md means -- deep-analyze it, bounded to only
                # this rare case (see sources/analysis.py's cost note). A
                # failure here is skipped, same non-fatal contract as Kademe 1.
                kademe2_started = time.perf_counter()
                try:
                    deep_context = {
                        "market_snapshot": markets[symbol],
                        "technical_snapshot": technicals[symbol],
                        "recent_headlines": new_headlines or db.recent_headlines(limit=5),
                    }
                    analysis = generate_deep_analysis(candidate, deep_context)
                    now_iso = datetime.now(UTC).isoformat()
                    db.insert_ai_call_log(
                        "kademe2_sonnet", attempted=1, succeeded=1,
                        duration_ms=(time.perf_counter() - kademe2_started) * 1000,
                        error_reason=None, called_at=now_iso,
                    )
                    db.insert_deep_analysis(candidate_id, analysis, now_iso)
                    candidate["deep_analysis"] = analysis

                    # Kademe 3: only escalate to the rarest, most expensive
                    # tier when Kademe 2 itself already called this "strong"
                    # -- see sources/proposal.py's own docstring for the
                    # full gate (direction + stop-loss availability checked
                    # there too).
                    if analysis["corroboration_strength"] == "strong":
                        kademe3_started = time.perf_counter()
                        try:
                            proposal = generate_final_proposal(candidate, analysis, deep_context)
                            now_iso = datetime.now(UTC).isoformat()
                            db.insert_ai_call_log(
                                "kademe3_opus", attempted=1, succeeded=1,
                                duration_ms=(time.perf_counter() - kademe3_started) * 1000,
                                error_reason=None, called_at=now_iso,
                            )
                            db.insert_final_proposal(candidate_id, proposal, now_iso)
                            candidate["final_proposal"] = proposal

                            # Aşama 3, Paper trading: a real proposal gets a
                            # simulated position, tracked against real prices
                            # from here on. No exchange client, no real
                            # money -- see paper_trading.py's own docstring.
                            # Risk Guard (section 7, "Değişmez Anayasa") has
                            # final say before any position, paper or
                            # otherwise -- concurrent-position cap and daily
                            # loss circuit breaker, checked every time.
                            if markets[symbol]:
                                risk_block = risk_guard_blocks_new_position(db, now=datetime.now(UTC))
                                if risk_block:
                                    print(f"[uyarı] Risk Guard: yeni pozisyon engellendi -- {risk_block}", file=sys.stderr)
                                else:
                                    position = open_position(
                                        candidate_id, proposal, markets[symbol]["mark_price"],
                                        deep_context["technical_snapshot"], symbol=symbol,
                                        available_notional=available_notional_usd(db),
                                    )
                                    # Aşama 5 goes first: it re-runs Risk Guard
                                    # itself, and must see the same state that
                                    # just cleared this paper position -- not
                                    # the state after that position filled a slot.
                                    # Aşama 5 skeleton (see approval.py):
                                    # additive, never a replacement for
                                    # paper trading -- evaluation.py's own
                                    # ready_for_asama5 measurement depends
                                    # on paper positions continuing to
                                    # close regardless. ASAMA5_ENABLED is
                                    # off by default, so this is a no-op
                                    # until deliberately turned on.
                                    if asama5_active(db):
                                        create_approval_request(
                                            db, candidate_id, proposal, markets[symbol]["mark_price"],
                                            deep_context["technical_snapshot"], symbol=symbol,
                                        )
                                    if position:
                                        db.insert_paper_position(position)
                                        candidate["paper_position"] = position
                        except ProposalError as error:
                            db.insert_ai_call_log(
                                "kademe3_opus", attempted=1, succeeded=0,
                                duration_ms=(time.perf_counter() - kademe3_started) * 1000,
                                error_reason=str(error)[:200], called_at=datetime.now(UTC).isoformat(),
                            )
                            print(f"[uyarı] Kademe 3 öneri başarısız: {error}", file=sys.stderr)
                except AnalysisError as error:
                    db.insert_ai_call_log(
                        "kademe2_sonnet", attempted=1, succeeded=0,
                        duration_ms=(time.perf_counter() - kademe2_started) * 1000,
                        error_reason=str(error)[:200], called_at=datetime.now(UTC).isoformat(),
                    )
                    print(f"[uyarı] Kademe 2 analiz başarısız: {error}", file=sys.stderr)

        expire_stale_requests(db)

        # Every cycle, regardless of whether a new candidate showed up:
        # check already-open paper positions (any tracked symbol) against
        # this cycle's current prices.
        current_prices = {symbol: m["mark_price"] for symbol, m in markets.items() if m}
        closed_positions = check_and_close_positions(db, current_prices) if current_prices else []

        # Daily digest + instant alerts (digest.py). Notification is a
        # side channel: whatever goes wrong there (network, a malformed
        # local config) must never fail the data-collection cycle.
        try:
            notify_after_cycle(db, candidates=all_candidates, closed_positions=closed_positions)
        except Exception as error:  # noqa: BLE001 -- deliberate boundary, see comment above
            print(f"[uyarı] bildirim adımı atlandı: {type(error).__name__}: {error}", file=sys.stderr)

        return render_report(
            onchain_events=onchain_events,
            market_snapshots=markets,
            sentiment_snapshot=sentiment,
            headlines=new_headlines,
            signal_candidates=all_candidates,
            closed_positions=closed_positions,
            abstentions=abstain_reasons,
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
