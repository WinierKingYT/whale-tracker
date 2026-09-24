"""Test-tooling entry point: a fake exchange feed running the REAL
pipeline (signal.py, sources/classify.py, sources/analysis.py,
sources/proposal.py, paper_trading.py, evaluation.py -- all unchanged)
against synthetic-but-realistic data instead of live network calls.

Why: Kademe 3's "strong" gate is rare against real data (see
sources/proposal.py's own docstring), so paper_trading.py and
evaluation.py have had almost nothing real to run against. This lets many
simulated observer cycles run in seconds instead of waiting weeks, to
actually exercise those code paths at volume and sanity-check the
mechanical pipeline's plausibility under a fabricated-but-plausible price
path -- not to replace real data, and never treated as it.

Writes to its OWN database (default data/simulation.db), never the real
data/whale_tracker.db -- synthetic data must never be mistaken for or
mixed with real observations.

AI (Kademe 1/2/3) calls are OFF by default -- pass --with-ai to enable
real Hermes/Sonnet/Opus CLI calls. Running many cycles fast would
otherwise fire many real AI calls against the user's own subscription
quota without them asking for that specifically each run (see
sources/analysis.py's own cost-measurement note). With AI off, a
synthetic stand-in produces plausibly-shaped, clearly-labeled-synthetic
Kademe 2/3 text -- but the deterministic risk math (stop-loss from
sources/proposal.py's real _compute_stop_loss, position sizing from its
real MAX_POSITION_SIZE_PCT) is never faked, only the AI free-text
judgment is."""

from __future__ import annotations

import argparse
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from whale_tracker.evaluation import evaluate_paper_trading, render_evaluation_report
from whale_tracker.observe import TRACKED_SYMBOLS
from whale_tracker.paper_trading import check_and_close_positions, open_position
from whale_tracker.report import render_report
from whale_tracker.signal import generate_candidates
from whale_tracker.simulation.market import MarketSimulator
from whale_tracker.simulation.news import NewsSimulator
from whale_tracker.simulation.onchain import OnchainSimulator
from whale_tracker.simulation.sentiment import SentimentSimulator
from whale_tracker.sources.analysis import AnalysisError, generate_deep_analysis
from whale_tracker.sources.classify import classify_top_events
from whale_tracker.sources.proposal import MAX_POSITION_SIZE_PCT, ProposalError, _compute_stop_loss, _no_action, generate_final_proposal
from whale_tracker.storage import Storage

DEFAULT_DB_PATH = Path(__file__).resolve().parents[2] / "data" / "simulation.db"
DEFAULT_CLASSIFY_LIMIT = 5
DEFAULT_CYCLE_MINUTES = 15


def _synthetic_deep_analysis(candidate: dict[str, Any]) -> dict[str, Any]:
    """Stand-in for Kademe 2 when --with-ai is off. corroboration_strength
    is derived from signal.py's own real mechanical confidence score
    (which we already trust -- it isn't AI), not gamed to force a
    particular outcome. The free text is clearly labeled synthetic so it
    can never be mistaken for a real AI judgment if ever inspected."""
    confidence = candidate["confidence"]
    if confidence >= 0.7:
        strength = "strong"
    elif confidence >= 0.4:
        strength = "moderate"
    else:
        strength = "weak"
    return {
        "assessment": f"[simülasyon, AI çağrısı yok] mekanik güven={confidence:.2f} temel alındı",
        "counter_argument": "[simülasyon] gerçek Kademe 2 analizi çalıştırılmadı",
        "risk_flags": ["simulated_no_ai"],
        "corroboration_strength": strength,
    }


def _synthetic_final_proposal(candidate: dict[str, Any], technical: dict[str, Any] | None) -> dict[str, Any]:
    """Stand-in for Kademe 3 when --with-ai is off. Reuses proposal.py's
    real, deterministic risk math (_compute_stop_loss, MAX_POSITION_SIZE_PCT,
    _no_action) unchanged -- only the AI free-text fields are faked."""
    if candidate["direction"] != "accumulation":
        return _no_action("[simülasyon] yön 'accumulation' değil")
    stop_loss_price = _compute_stop_loss(technical)
    if stop_loss_price is None:
        return _no_action("[simülasyon] teknik anlık görüntü/destek seviyesi yok")
    return {
        "action": "long_candidate",
        "reason": None,
        "max_position_size_pct": MAX_POSITION_SIZE_PCT,
        "stop_loss_price": stop_loss_price,
        "entry_rationale": "[simülasyon, AI çağrısı yok] mekanik sinyal temel alındı",
        "worst_case_scenario": "[simülasyon] gerçek Kademe 3 analizi çalıştırılmadı",
        "counter_arguments": ["[simülasyon]"],
        "conviction": "medium",
    }


def run_cycle(
    db: Storage,
    markets: dict[str, MarketSimulator],
    onchain_sim: OnchainSimulator,
    sentiment_sim: SentimentSimulator,
    news_sim: NewsSimulator,
    *,
    cycle_minutes: int = DEFAULT_CYCLE_MINUTES,
    with_ai: bool = False,
    classify_limit: int = DEFAULT_CLASSIFY_LIMIT,
) -> dict[str, Any]:
    """One simulated observer cycle -- mirrors observe.py's run_once body,
    sourced from simulators instead of live network calls."""
    market_snapshots: dict[str, dict | None] = {}
    technical_snapshots: dict[str, dict | None] = {}
    for symbol, sim in markets.items():
        sim.tick(minutes=cycle_minutes)
        market_snapshots[symbol] = sim.market_snapshot()
        technical_snapshots[symbol] = sim.technical_snapshot()
        db.insert_market_snapshot(market_snapshots[symbol])
        db.insert_technical_snapshot(technical_snapshots[symbol])

    # All generators must share ONE advancing simulated clock (the market
    # simulators', which all tick together above) -- found by actually
    # running a 3000-cycle simulation and seeing signal.py's 24h flow
    # window come out almost entirely one-directional: onchain/sentiment/
    # news were defaulting to real wall-clock time instead, so a "24h
    # window" over a run that takes two real minutes never rolls off a
    # single event, turning it into an ever-growing cumulative sum whose
    # random-walk drift gets locked in early instead of a genuine rolling
    # window. Same reasoning is why generate_candidates/
    # check_and_close_positions below take an explicit `now=` too --
    # every real-time-vs-simulated-time seam has to be closed, not just
    # the onchain/sentiment/news ones.
    simulated_now_dt = next(iter(markets.values())).now
    simulated_now = simulated_now_dt.isoformat()

    sentiment = sentiment_sim.tick(observed_at=simulated_now)
    db.insert_sentiment_snapshot(sentiment)

    onchain_events = [e for e in onchain_sim.tick_events(observed_at=simulated_now) if db.insert_onchain_event(e)]
    new_headlines = [h for h in news_sim.tick_headlines(observed_at=simulated_now) if db.insert_headline(h)]

    classifications = classify_top_events(onchain_events, limit=classify_limit) if (with_ai and onchain_events) else {}
    for index, classification in classifications.items():
        event = onchain_events[index]
        db.insert_classification(event["tx_hash"], event["log_index"], classification, simulated_now)
        event["classification"] = classification

    all_candidates: list[dict[str, Any]] = []
    for symbol in markets:
        candidates = generate_candidates(db, symbol=symbol, now=simulated_now_dt)
        all_candidates.extend(candidates)
        for candidate in candidates:
            candidate_id = db.insert_signal_candidate(candidate)
            deep_context = {
                "market_snapshot": market_snapshots[symbol],
                "technical_snapshot": technical_snapshots[symbol],
                "recent_headlines": new_headlines or db.recent_headlines(limit=5),
            }
            if with_ai:
                # Real AI calls, unlike the synthetic default -- worth the
                # same quota tracking observe.py does, so a --with-ai
                # simulation run's status.py numbers stay honest too.
                kademe2_started = time.perf_counter()
                try:
                    analysis = generate_deep_analysis(candidate, deep_context)
                    db.insert_ai_call_log(
                        "kademe2_sonnet", attempted=1, succeeded=1,
                        duration_ms=(time.perf_counter() - kademe2_started) * 1000,
                        error_reason=None, called_at=simulated_now,
                    )
                except AnalysisError as error:
                    db.insert_ai_call_log(
                        "kademe2_sonnet", attempted=1, succeeded=0,
                        duration_ms=(time.perf_counter() - kademe2_started) * 1000,
                        error_reason=str(error)[:200], called_at=simulated_now,
                    )
                    continue
            else:
                analysis = _synthetic_deep_analysis(candidate)
            db.insert_deep_analysis(candidate_id, analysis, simulated_now)
            candidate["deep_analysis"] = analysis

            if analysis["corroboration_strength"] == "strong":
                if with_ai:
                    kademe3_started = time.perf_counter()
                    try:
                        proposal = generate_final_proposal(candidate, analysis, deep_context)
                        db.insert_ai_call_log(
                            "kademe3_opus", attempted=1, succeeded=1,
                            duration_ms=(time.perf_counter() - kademe3_started) * 1000,
                            error_reason=None, called_at=simulated_now,
                        )
                    except ProposalError as error:
                        db.insert_ai_call_log(
                            "kademe3_opus", attempted=1, succeeded=0,
                            duration_ms=(time.perf_counter() - kademe3_started) * 1000,
                            error_reason=str(error)[:200], called_at=simulated_now,
                        )
                        continue
                else:
                    proposal = _synthetic_final_proposal(candidate, technical_snapshots[symbol])
                db.insert_final_proposal(candidate_id, proposal, simulated_now)
                candidate["final_proposal"] = proposal

                if market_snapshots[symbol]:
                    position = open_position(
                        candidate_id, proposal, market_snapshots[symbol]["mark_price"],
                        technical_snapshots[symbol], symbol=symbol, now=simulated_now_dt,
                    )
                    if position:
                        db.insert_paper_position(position)
                        candidate["paper_position"] = position

    current_prices = {symbol: snap["mark_price"] for symbol, snap in market_snapshots.items() if snap}
    closed_positions = (
        check_and_close_positions(db, current_prices, now=simulated_now_dt) if current_prices else []
    )

    return {
        "onchain_events": onchain_events,
        "market_snapshots": market_snapshots,
        "sentiment_snapshot": sentiment,
        "headlines": new_headlines,
        "candidates": all_candidates,
        "closed_positions": closed_positions,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="whale-tracker simülasyon -- gerçekçi sahte veriyle gerçek pipeline testi")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--cycles", type=int, default=100, help="Kaç simüle gözlem döngüsü çalıştırılsın")
    parser.add_argument("--cycle-minutes", type=int, default=DEFAULT_CYCLE_MINUTES)
    parser.add_argument("--seed", type=int, default=None, help="Tekrarlanabilirlik için sabit seed")
    parser.add_argument(
        "--with-ai", action="store_true",
        help="Kademe 1/2/3 için GERÇEK Hermes/Sonnet/Opus çağrıları yap (kotanı kullanır, yavaş). "
             "Varsayılan: sentetik/açıkça-etiketli sahte metin, gerçek risk matematiği (stop-loss, pozisyon "
             "büyüklüğü) değişmeden kalır.",
    )
    parser.add_argument("--min-usd", type=float, default=1_000_000.0)
    parser.add_argument("--classify-limit", type=int, default=DEFAULT_CLASSIFY_LIMIT)
    parser.add_argument("--print-every", type=int, default=0, help="Her N döngüde bir tam rapor yazdır (0 = hiç)")
    args = parser.parse_args()

    with Storage(args.db) as db:
        markets = {symbol: MarketSimulator(symbol, seed=args.seed) for symbol in TRACKED_SYMBOLS}
        onchain_sim = OnchainSimulator(seed=args.seed, min_usd=args.min_usd)
        sentiment_sim = SentimentSimulator(seed=args.seed)
        news_sim = NewsSimulator(seed=args.seed)

        for cycle in range(1, args.cycles + 1):
            result = run_cycle(
                db, markets, onchain_sim, sentiment_sim, news_sim,
                cycle_minutes=args.cycle_minutes, with_ai=args.with_ai, classify_limit=args.classify_limit,
            )
            if args.print_every and cycle % args.print_every == 0:
                print(f"--- döngü {cycle}/{args.cycles} ---")
                print(render_report(
                    onchain_events=result["onchain_events"], market_snapshots=result["market_snapshots"],
                    sentiment_snapshot=result["sentiment_snapshot"], headlines=result["headlines"],
                    signal_candidates=result["candidates"], closed_positions=result["closed_positions"],
                ))

        scorecard = evaluate_paper_trading(db)

    print(f"\n{args.cycles} simüle döngü tamamlandı (db: {args.db}, with_ai={args.with_ai})")
    print(render_evaluation_report(scorecard))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
