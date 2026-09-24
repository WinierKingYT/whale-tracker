"""Backtest entry point: `python -m whale_tracker.backtest --days 30`.

Downloads (once, cached) the last N days of real market/funding/
Fear&Greed/exchange-flow history, replays it cycle by cycle through
simulate.run_cycle -- the same real pipeline simulate.py drives -- into
its OWN database (data/backtest.db, recreated each run, never the real
data/whale_tracker.db), then scores the result two ways: the plan's own
Asama 4 scorecard (evaluation.py) and the random-entry baseline
(baseline.py), which is the one that actually answers "is there edge"."""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from whale_tracker.backtest.baseline import random_entry_baseline
from whale_tracker.backtest.history import (
    DEFAULT_CHUNK_BLOCKS,
    ArchiveAccessError,
    block_at_or_after,
    check_archive_access,
    fetch_exchange_flow_events,
    fetch_fear_greed_history,
    fetch_funding_history,
    fetch_klines,
)
from whale_tracker.backtest.replay import (
    HistoricalMarketReplay,
    HistoricalOnchainReplay,
    HistoricalSentimentReplay,
    NoNewsReplay,
)
from whale_tracker.evaluation import evaluate_paper_trading, render_evaluation_report
from whale_tracker.observe import TRACKED_SYMBOLS
from whale_tracker.simulate import DEFAULT_CYCLE_MINUTES, run_cycle
from whale_tracker.sources.onchain import DEFAULT_MIN_USD
from whale_tracker.sources.technical import DEFAULT_LOOKBACK_DAYS
from whale_tracker.storage import Storage

DEFAULT_DB_PATH = Path(__file__).resolve().parents[3] / "data" / "backtest.db"
DEFAULT_DAYS = 30

LIMITATIONS = (
    "Kademe 2/3 gerçek Sonnet/Opus değil, simulate.py'nin sentetik vekilleri (mekanik güven >= 0.7 -> 'strong'): "
    "bu backtest mekanik sinyali ve risk kurallarını ölçer, AI yargısını değil.",
    "Geçmiş haber arşivi yok: olumsuz-haber cezası hiç tetiklenmez (birikim adayları üretimdekinden biraz daha kolay geçer).",
    "Bilinen cüzdan listesi BUGÜNKÜ liste: geçmişte farklı cüzdan kullanılmış olabilir (hayatta kalan yanlılığı).",
    "Funding, üretimdeki anlık lastFundingRate değil 8 saatlik yerleşik oran; fiyat, mark price değil 15m futures mum kapanışı.",
    "Open interest tekrar oynatılmıyor (hiçbir skorda kullanılmıyor).",
    "Zincir üstü olay zamanı = blok zamanı; üretimde tarama zamanı (en fazla ~15 dk sonra).",
)


def _progress(message: str) -> None:
    print(f"[backtest] {message}", file=sys.stderr, flush=True)


def load_history(
    start: datetime, end: datetime, *, min_usd: float, chunk_blocks: int | None = None,
) -> dict[str, Any]:
    """Everything the replay needs, including warm-up before `start`:
    30+ days of daily candles for support/resistance, a day of 15m
    candles for the first cycle's partial-day candle, and a day of
    onchain flow so the first cycle's 24h window is already full."""
    markets: dict[str, dict[str, Any]] = {}
    for symbol in TRACKED_SYMBOLS:
        _progress(f"{symbol} fiyat/funding geçmişi")
        markets[symbol] = {
            "daily_klines": fetch_klines(symbol, "1d", start - timedelta(days=DEFAULT_LOOKBACK_DAYS + 2), end),
            "klines_15m": fetch_klines(symbol, "15m", start - timedelta(days=1), end),
            "funding_history": fetch_funding_history(symbol, start - timedelta(days=2), end),
        }
    _progress("Fear&Greed geçmişi")
    fear_greed = fetch_fear_greed_history()
    _progress("blok aralığı aranıyor")
    start_block = block_at_or_after(start - timedelta(days=1))
    end_block = block_at_or_after(end) - 1
    check_archive_access(start_block)
    _progress(f"zincir üstü akış: blok {start_block}-{end_block} (ilk seferde uzun sürer, sonra önbellekten)")
    events = fetch_exchange_flow_events(
        start_block, end_block, min_usd=min_usd, chunk_blocks=chunk_blocks, progress=_progress,
    )
    return {"markets": markets, "fear_greed": fear_greed, "events": events}


def replay(history: dict[str, Any], start: datetime, days: int, db_path: Path) -> dict[str, Any]:
    db_path.unlink(missing_ok=True)
    counts: Counter[str] = Counter()
    with Storage(db_path) as db:
        markets = {
            symbol: HistoricalMarketReplay(symbol, start=start, **data)
            for symbol, data in history["markets"].items()
        }
        onchain = HistoricalOnchainReplay(history["events"])
        sentiment = HistoricalSentimentReplay(history["fear_greed"])
        news = NoNewsReplay()

        cycles = days * 24 * 60 // DEFAULT_CYCLE_MINUTES
        for cycle in range(1, cycles + 1):
            result = run_cycle(db, markets, onchain, sentiment, news, with_ai=False)
            for candidate in result["candidates"]:
                counts[f"aday_{candidate['direction']}"] += 1
                if candidate.get("deep_analysis", {}).get("corroboration_strength") == "strong":
                    counts["strong"] += 1
                if candidate.get("final_proposal", {}).get("action") == "long_candidate":
                    counts["long_öneri"] += 1
                if candidate.get("paper_position"):
                    counts["açılan_pozisyon"] += 1
            if cycle % (96 * 5) == 0:
                _progress(f"tekrar oynatma: {cycle}/{cycles} döngü")

        scorecard = evaluate_paper_trading(db)
        closed = [p for p in db.all_paper_positions() if p["status"] != "open"]
        baseline = random_entry_baseline(db, closed)
        exit_mix = Counter(p["status"] for p in closed)
    return {"counts": counts, "scorecard": scorecard, "baseline": baseline, "exit_mix": exit_mix}


def render(result: dict[str, Any], *, start: datetime, end: datetime) -> str:
    counts = result["counts"]
    lines = [
        f"=== whale-tracker backtest: {start.date()} -> {end.date()} (gerçek geçmiş veri) ===", "",
        f"Aday: birikim={counts['aday_accumulation']}, dağıtım={counts['aday_distribution']}; "
        f"strong={counts['strong']}, long önerisi={counts['long_öneri']}, açılan pozisyon={counts['açılan_pozisyon']}",
        f"Çıkış dağılımı: {dict(result['exit_mix']) or '(kapanan yok)'}", "",
        render_evaluation_report(result["scorecard"]), "",
        "=== Rastgele giriş karşılaştırması (asıl kenar testi) ===",
    ]
    baseline = result["baseline"]
    if baseline is None:
        lines.append("Kapanan pozisyon yok -- karşılaştırılacak bir şey yok.")
    else:
        lines += [
            f"Strateji, işlem başına ort. getiri: {baseline['strategy_mean_pnl_pct']:+.3%} "
            f"({baseline['trades_per_trial']} işlem)",
            f"Aynı dönemde rastgele girişler (aynı stop/hedef/süre kuralları, {baseline['trials']} deneme): "
            f"{baseline['random_mean_pnl_pct']:+.3%} ± {baseline['random_stdev_of_means']:.3%}",
            f"p-değeri (rastgele denemelerin stratejiye eşit ya da daha iyi olma oranı): {baseline['p_value']:.3f}",
        ]
        if baseline["trades_per_trial"] < 10:
            lines.append("[UYARI] 10'dan az işlem -- bu karşılaştırma istatistiksel olarak çok zayıf.")
        verdict = (
            "sinyalin zamanlaması rastgeleden anlamlı şekilde iyi" if baseline["p_value"] < 0.05
            else "sinyalin zamanlaması rastgele girişten ayırt edilemiyor (bu dönem, bu veriyle)"
        )
        lines.append(f"Sonuç: {verdict}.")
    lines += ["", "Sınırlamalar:"] + [f"  - {item}" for item in LIMITATIONS]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="whale-tracker backtest -- gerçek geçmiş veriyle gerçek pipeline")
    parser.add_argument("--days", type=int, default=DEFAULT_DAYS)
    parser.add_argument(
        "--end", type=lambda s: datetime.fromisoformat(s).replace(tzinfo=UTC), default=None,
        help="Bitiş günü (YYYY-MM-DD, UTC). Varsayılan: bugün 00:00 UTC.",
    )
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--min-usd", type=float, default=DEFAULT_MIN_USD)
    parser.add_argument(
        "--chunk-blocks", type=int, default=None,
        help=f"Önbellek parçası başına blok sayısı (varsayılan: Alchemy'de ~3 gün, diğerlerinde "
             f"{DEFAULT_CHUNK_BLOCKS} -- eth_getLogs'u RPC'nin kendi aralık sınırına göre küçült).",
    )
    args = parser.parse_args()

    end = args.end or datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    start = end - timedelta(days=args.days)
    try:
        history = load_history(start, end, min_usd=args.min_usd, chunk_blocks=args.chunk_blocks)
    except ArchiveAccessError as error:
        print(f"[backtest] {error}", file=sys.stderr)
        return 2
    result = replay(history, start, args.days, args.db)
    print(render(result, start=start, end=end))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
