"""Risk-calibration batch runner: runs the simulated pipeline across many
independent seeded price paths (each in its own throwaway temp database,
never data/simulation.db or the real database) and aggregates the
resulting Asama 4 scorecards.

Why this exists: a single simulate.py run (seed=99, 1500 cycles) showed
avg win (+0.36%) far smaller than avg loss (-4.23%) -- net losing despite
a 69.6% win rate. One random price path can't answer whether that's a
real structural property of the current risk-rule calibration
(sources/proposal.py's STOP_LOSS_SUPPORT_BUFFER_PCT, paper_trading.py's
TAKE_PROFIT_RESISTANCE_BUFFER_PCT) or just how that one seed happened to
land. This runs N independent seeds and reports the pattern across all
of them.

Still not real data, still not a reason to change the live risk
constants on its own -- this is a diagnostic, not a tuner. If the pattern
holds across many independent random walks, that's a real, actionable
signal about the CURRENT buffers being asymmetric (tight take-profit,
wide stop-loss) under GBM-like price action; if it doesn't, the earlier
single run was just an unlucky draw."""

from __future__ import annotations

import argparse
import statistics
import tempfile
from pathlib import Path
from typing import Any

from whale_tracker.evaluation import evaluate_paper_trading
from whale_tracker.observe import TRACKED_SYMBOLS
from whale_tracker.simulate import run_cycle
from whale_tracker.simulation.market import MarketSimulator
from whale_tracker.simulation.news import NewsSimulator
from whale_tracker.simulation.onchain import OnchainSimulator
from whale_tracker.simulation.sentiment import SentimentSimulator
from whale_tracker.storage import Storage

# Keeps a default `calibrate.py` invocation under a few minutes; pass
# --runs/--cycles for a more statistically confident (slower) pass.
DEFAULT_NUM_RUNS = 10
DEFAULT_CYCLES_PER_RUN = 800


def run_one(seed: int, *, cycles: int, min_usd: float) -> dict[str, Any]:
    """One independent simulated price path, in its own temp DB that is
    deleted when this returns -- never accumulates, never shared across
    seeds, never touches data/simulation.db."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = Path(tmp_dir) / "calibration.db"
        with Storage(db_path) as db:
            markets = {symbol: MarketSimulator(symbol, seed=seed) for symbol in TRACKED_SYMBOLS}
            onchain_sim = OnchainSimulator(seed=seed, min_usd=min_usd)
            sentiment_sim = SentimentSimulator(seed=seed)
            news_sim = NewsSimulator(seed=seed)
            for _ in range(cycles):
                run_cycle(db, markets, onchain_sim, sentiment_sim, news_sim, with_ai=False)
            scorecard = evaluate_paper_trading(db)
    scorecard["seed"] = seed
    return scorecard


def run_batch(num_runs: int, *, cycles: int, min_usd: float, base_seed: int = 0) -> list[dict[str, Any]]:
    return [run_one(base_seed + i, cycles=cycles, min_usd=min_usd) for i in range(num_runs)]


def _mean(values: list[float]) -> float | None:
    return round(statistics.mean(values), 4) if values else None


def summarize(scorecards: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate across runs. Runs with zero closed positions (no
    'strong' candidate showed up in that price path) are excluded from
    the means but counted separately -- they carry no P&L information,
    averaging in a None/0 would misrepresent the runs that did trade."""
    with_data = [s for s in scorecards if s["closed_position_count"] > 0]

    win_rates = [s["win_rate"] for s in with_data]
    strategy_returns = [s["strategy_return_pct"] for s in with_data]
    btc_hold_returns = [s["btc_hold_return_pct"] for s in with_data if s["btc_hold_return_pct"] is not None]
    avg_wins = [s["avg_win_pct"] for s in with_data if s["avg_win_pct"] is not None]
    avg_losses = [s["avg_loss_pct"] for s in with_data if s["avg_loss_pct"] is not None]
    drawdowns = [s["max_drawdown_pct"] for s in with_data]
    closed_counts = [s["closed_position_count"] for s in with_data]
    beats_btc_hold_flags = [s["beats_btc_hold"] for s in with_data if s["beats_btc_hold"] is not None]

    return {
        "num_runs": len(scorecards),
        "runs_with_closed_positions": len(with_data),
        "runs_with_no_data": len(scorecards) - len(with_data),
        "mean_closed_positions": _mean(closed_counts),
        "mean_win_rate": _mean(win_rates),
        "mean_avg_win_pct": _mean(avg_wins),
        "mean_avg_loss_pct": _mean(avg_losses),
        "mean_strategy_return_pct": _mean(strategy_returns),
        "mean_btc_hold_return_pct": _mean(btc_hold_returns),
        "mean_max_drawdown_pct": _mean(drawdowns),
        "pct_runs_beating_btc_hold": (
            round(sum(1 for f in beats_btc_hold_flags if f) / len(beats_btc_hold_flags), 4)
            if beats_btc_hold_flags else None
        ),
        "pct_runs_net_positive": (
            round(sum(1 for r in strategy_returns if r > 0) / len(strategy_returns), 4)
            if strategy_returns else None
        ),
    }


def render_summary(summary: dict[str, Any]) -> str:
    lines = ["=== whale-tracker risk kalibrasyonu -- çoklu-seed özet ===", ""]
    lines.append(
        f"Toplam çalıştırma: {summary['num_runs']}, "
        f"kapanmış pozisyonu olan: {summary['runs_with_closed_positions']}"
    )
    if summary["runs_with_no_data"]:
        lines.append(f"  ({summary['runs_with_no_data']} çalıştırmada hiç 'strong' aday çıkmadı)")
    if not summary["runs_with_closed_positions"]:
        lines.append("Hiçbir çalıştırmada pozisyon kapanmadı -- --cycles değerini artırın.")
        return "\n".join(lines)

    lines.append(f"Ortalama kapanmış pozisyon/çalıştırma: {summary['mean_closed_positions']:.1f}")
    lines.append(f"Ortalama isabet oranı: {summary['mean_win_rate']:.1%}")
    lines.append(f"Ortalama kazanç: {summary['mean_avg_win_pct']:+.2%}, ortalama kayıp: {summary['mean_avg_loss_pct']:+.2%}")
    lines.append(f"Ortalama strateji getirisi: {summary['mean_strategy_return_pct']:+.2%}")
    if summary["mean_btc_hold_return_pct"] is not None:
        lines.append(f"Ortalama BTC-hold getirisi: {summary['mean_btc_hold_return_pct']:+.2%}")
    lines.append(f"Ortalama maksimum düşüş: {summary['mean_max_drawdown_pct']:.2%}")
    if summary["pct_runs_beating_btc_hold"] is not None:
        lines.append(f"BTC-hold'u geçen çalıştırma oranı: {summary['pct_runs_beating_btc_hold']:.1%}")
    if summary["pct_runs_net_positive"] is not None:
        lines.append(f"Net pozitif getirili çalıştırma oranı: {summary['pct_runs_net_positive']:.1%}")

    avg_win = summary["mean_avg_win_pct"]
    avg_loss = summary["mean_avg_loss_pct"]
    if avg_win is not None and avg_loss is not None and avg_win < abs(avg_loss) * 0.5:
        lines.append("")
        lines.append(
            "[BULGU] Ortalama kazanç, ortalama kayıptan tutarlı şekilde çok küçük -- bu, mevcut "
            "stop-loss/take-profit tamponlarının (proposal.py/paper_trading.py) sıkı hedef + geniş "
            "stop asimetrisinin tek seferlik şans değil, tekrarlayan bir kalıp olduğuna işaret ediyor. "
            "Gerçek para öncesi (Aşama 5) bu kalibrasyon yeniden gözden geçirilmeli."
        )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="whale-tracker risk kalibrasyonu -- çoklu-seed batch simülasyon")
    parser.add_argument("--runs", type=int, default=DEFAULT_NUM_RUNS)
    parser.add_argument("--cycles", type=int, default=DEFAULT_CYCLES_PER_RUN)
    parser.add_argument("--base-seed", type=int, default=0)
    parser.add_argument("--min-usd", type=float, default=1_000_000.0)
    args = parser.parse_args()

    scorecards = run_batch(args.runs, cycles=args.cycles, min_usd=args.min_usd, base_seed=args.base_seed)
    print(render_summary(summarize(scorecards)))
    print("\nÇalıştırma bazında:")
    for scorecard in scorecards:
        if scorecard["closed_position_count"] == 0:
            print(f"  seed={scorecard['seed']}: (pozisyon yok)")
            continue
        btc_hold = scorecard["btc_hold_return_pct"]
        btc_hold_text = f", btc_hold={btc_hold:+.2%}" if btc_hold is not None else ""
        print(
            f"  seed={scorecard['seed']}: {scorecard['closed_position_count']} pozisyon, "
            f"isabet={scorecard['win_rate']:.1%}, getiri={scorecard['strategy_return_pct']:+.2%}{btc_hold_text}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
