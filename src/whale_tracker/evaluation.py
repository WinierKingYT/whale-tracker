"""Asama 4, Degerlendirme (see docs/PROJECT-PLAN.md section 9 -- "Basari
Kriteri"): score closed paper positions against the plan's own three
criteria, none of which is "made money":
  - isabet orani ve ortalama kazanc/kayip orani (win rate, win/loss ratio)
  - maksimum dusus (drawdown) kontrol altinda mi
  - ayni donemde sadece BTC tutmaktan daha iyi mi

Built ahead of having real closed positions (Kademe 3's "strong" gate is
rare, see proposal.py) so the measurement is ready and tested the moment
the first few trades close, rather than improvised later under whatever
data happens to exist by then.

Two deliberate first-pass simplifications, both documented so they don't
get mistaken for more rigor than they have:
- strategy_return_pct is simple sum-of-pnl / starting capital, not
  compounded -- fine while positions are small (~1% of capital) and
  rarely overlap, would need revisiting at higher position counts/overlap.
- The BTC-hold comparison uses market_snapshots for BTCUSDT specifically
  (storage.market_snapshot_near, storage.latest_market_snapshot) as the
  period's start/end price -- section 9's own wording is "sadece BTC
  tutmaktan daha iyi mi," always BTC regardless of which symbols the
  strategy actually traded (ETH support added candidates/positions can be
  ETHUSDT now, see signal.py/paper_trading.py). "Same period" here means
  "first position opened to last position closed," a first-pass proxy for
  a fixed-calendar window, not the window itself."""

from __future__ import annotations

import argparse
import statistics
from pathlib import Path
from typing import Any

from whale_tracker.backtest.baseline import random_entry_baseline
from whale_tracker.execution import EXIT_EXPIRY, net_return_pct
from whale_tracker.paper_trading import VIRTUAL_CAPITAL_USD
from whale_tracker.storage import Storage

DEFAULT_DB_PATH = Path(__file__).resolve().parents[2] / "data" / "whale_tracker.db"

# Plan says "birkac hafta sonuclar olculur" -- a count-based floor as a
# simple, first-pass proxy for "enough trades to mean anything," not a
# statistically derived threshold. Below this, numbers are still shown
# but flagged low-confidence rather than withheld.
MIN_POSITIONS_FOR_CONFIDENCE = 10

# Third condition for ready_for_asama5 (added 2026-09-25): the strategy's
# entries must beat random-time entries under the same exit rules
# (backtest/baseline.py, circular-shift p-value). Beating BTC-hold alone
# proved insufficient: in the 2025-09..2026-03 backtest a mostly-cash
# strategy LOST money (-0.95%) yet "beat" a -34.7% BTC-hold, and the gate
# said ready. This only ever tightens the plan's own criterion.
ASAMA5_EDGE_P_VALUE = 0.05


def evaluate_paper_trading(storage: Any) -> dict[str, Any]:
    """Return the Asama 4 scorecard for all paper positions recorded so
    far. Returns insufficient_data=True (with counts, nothing else) when
    no position has closed yet -- the expected, common state early on,
    not an error."""
    positions = storage.all_paper_positions()
    open_count = sum(1 for p in positions if p["status"] == "open")
    closed = sorted((p for p in positions if p["status"] != "open"), key=lambda p: p["closed_at"])

    if not closed:
        return {
            "closed_position_count": 0, "open_position_count": open_count,
            "insufficient_data": True, "edge_test": None, "ready_for_asama5": False,
        }

    wins = [p for p in closed if p["pnl_usd"] > 0]
    losses = [p for p in closed if p["pnl_usd"] <= 0]
    win_rate = len(wins) / len(closed)
    avg_win_pct = statistics.mean(p["pnl_pct"] for p in wins) if wins else None
    avg_loss_pct = statistics.mean(p["pnl_pct"] for p in losses) if losses else None
    win_loss_ratio = (
        abs(avg_win_pct / avg_loss_pct) if avg_win_pct is not None and avg_loss_pct not in (None, 0) else None
    )

    equity = VIRTUAL_CAPITAL_USD
    peak = equity
    max_drawdown_pct = 0.0
    for position in closed:
        equity += position["pnl_usd"]
        peak = max(peak, equity)
        if peak > 0:
            max_drawdown_pct = max(max_drawdown_pct, (peak - equity) / peak)

    total_pnl_usd = round(sum(p["pnl_usd"] for p in closed), 2)
    strategy_return_pct = total_pnl_usd / VIRTUAL_CAPITAL_USD

    first_position = min(positions, key=lambda p: p["opened_at"])
    btc_start = storage.market_snapshot_near("BTCUSDT", first_position["opened_at"])
    # Anchored to the last position's own closed_at, not "now" -- observe.py
    # inserts a fresh BTCUSDT snapshot on every scheduled cycle regardless
    # of trading activity, so latest_market_snapshot() would keep pulling
    # in post-close BTC movement into this comparison the longer the
    # scheduler runs after the strategy went quiet. "Same period" (this
    # module's own stated definition) means "first position opened to
    # last position closed," not "...to whenever this report is run."
    # Found by code review, not by a real failure yet.
    btc_end = storage.market_snapshot_near("BTCUSDT", closed[-1]["closed_at"])
    if btc_start and btc_end and btc_start["mark_price"]:
        # One round trip through the same execution model the strategy's
        # trades pay (execution.py) -- a fair benchmark, not a free one.
        btc_hold_return_pct = round(
            net_return_pct(btc_start["mark_price"], EXIT_EXPIRY, btc_end["mark_price"], btc_end["mark_price"])[1], 4,
        )
        beats_btc_hold = strategy_return_pct > btc_hold_return_pct
    else:
        # No BTCUSDT market history covering this window -- can't score
        # against section 9's own criterion, report None rather than a
        # fabricated comparison.
        btc_hold_return_pct = None
        beats_btc_hold = None

    by_symbol: dict[str, dict[str, Any]] = {}
    for symbol in sorted({p.get("symbol", "BTCUSDT") for p in closed}):
        symbol_closed = [p for p in closed if p.get("symbol", "BTCUSDT") == symbol]
        symbol_wins = [p for p in symbol_closed if p["pnl_usd"] > 0]
        by_symbol[symbol] = {
            "closed_position_count": len(symbol_closed),
            "win_rate": round(len(symbol_wins) / len(symbol_closed), 4),
            "total_pnl_usd": round(sum(p["pnl_usd"] for p in symbol_closed), 2),
        }

    insufficient_data = len(closed) < MIN_POSITIONS_FOR_CONFIDENCE
    edge_test = random_entry_baseline(storage, closed)
    beats_random_entries = edge_test is not None and edge_test["p_value"] < ASAMA5_EDGE_P_VALUE
    return {
        "closed_position_count": len(closed),
        "open_position_count": open_count,
        "insufficient_data": insufficient_data,
        "win_rate": round(win_rate, 4),
        "avg_win_pct": round(avg_win_pct, 4) if avg_win_pct is not None else None,
        "avg_loss_pct": round(avg_loss_pct, 4) if avg_loss_pct is not None else None,
        "win_loss_ratio": round(win_loss_ratio, 3) if win_loss_ratio is not None else None,
        "total_pnl_usd": total_pnl_usd,
        "strategy_return_pct": round(strategy_return_pct, 4),
        "max_drawdown_pct": round(max_drawdown_pct, 4),
        "btc_hold_return_pct": btc_hold_return_pct,
        "beats_btc_hold": beats_btc_hold,
        "by_symbol": by_symbol,
        "edge_test": edge_test,
        # PROJECT-PLAN.md's own gate (enough sample, beats BTC-hold --
        # section 9) plus ASAMA5_EDGE_P_VALUE's condition: entries must
        # beat random-time entries. No win-rate or drawdown thresholds of
        # its own beyond that.
        "ready_for_asama5": (not insufficient_data) and beats_btc_hold is True and beats_random_entries,
    }


def render_evaluation_report(scorecard: dict[str, Any]) -> str:
    lines = ["=== whale-tracker Aşama 4 değerlendirme ===", ""]
    if scorecard["insufficient_data"] and scorecard["closed_position_count"] == 0:
        lines.append(f"Henüz kapanmış kağıt pozisyon yok (açık: {scorecard['open_position_count']}).")
        lines.append("Kademe 3 eşiği ('strong') nadir tetiklendiği için bu beklenen bir durum.")
        return "\n".join(lines)

    if scorecard["insufficient_data"]:
        lines.append(
            f"[UYARI] Yalnızca {scorecard['closed_position_count']} kapanmış pozisyon "
            f"(< {MIN_POSITIONS_FOR_CONFIDENCE}) -- sayılar düşük güvenilirlikte, yorumlarken dikkatli olun."
        )
        lines.append("")

    lines.append(f"Kapanmış pozisyon: {scorecard['closed_position_count']}, açık: {scorecard['open_position_count']}")
    lines.append(f"İsabet oranı: {scorecard['win_rate']:.1%}")
    if scorecard["win_loss_ratio"] is not None:
        lines.append(
            f"Ortalama kazanç/kayıp oranı: {scorecard['win_loss_ratio']:.2f} "
            f"(ort. kazanç {scorecard['avg_win_pct']:+.2%}, ort. kayıp {scorecard['avg_loss_pct']:+.2%})"
        )
    lines.append(f"Toplam P&L: ${scorecard['total_pnl_usd']:,.2f} (${VIRTUAL_CAPITAL_USD:,.0f} sanal sermaye üzerinden)")
    lines.append(f"Strateji getirisi: {scorecard['strategy_return_pct']:+.2%}")
    lines.append(f"Maksimum düşüş (drawdown): {scorecard['max_drawdown_pct']:.2%}")
    if scorecard["btc_hold_return_pct"] is None:
        lines.append("Aynı dönemde BTC-hold getirisi: (BTCUSDT piyasa geçmişi yok, karşılaştırılamıyor)")
    else:
        lines.append(f"Aynı dönemde BTC-hold getirisi: {scorecard['btc_hold_return_pct']:+.2%}")
        verdict = "EVET" if scorecard["beats_btc_hold"] else "HAYIR"
        lines.append(f"BTC-hold'u geçiyor mu: {verdict}")
        if not scorecard["beats_btc_hold"]:
            lines.append("  -> PROJECT-PLAN.md section 9: 'sadece BTC tutmak' yeniyorsa gerçek parayı artırmayız.")

    by_symbol = scorecard.get("by_symbol") or {}
    if len(by_symbol) > 1:
        lines.append("")
        lines.append("Sembol bazında:")
        for symbol, stats in by_symbol.items():
            lines.append(
                f"  {symbol}: {stats['closed_position_count']} pozisyon, "
                f"isabet={stats['win_rate']:.1%}, P&L=${stats['total_pnl_usd']:,.2f}"
            )

    edge_test = scorecard.get("edge_test")
    if edge_test:
        lines.append(
            f"Rastgele girişlere karşı: işlem başına {edge_test['strategy_mean_pnl_pct']:+.2%} vs "
            f"{edge_test['random_mean_pnl_pct']:+.2%} (p={edge_test['p_value']:.3f})"
        )

    lines.append("")
    if scorecard["ready_for_asama5"]:
        lines.append(
            f"[HAZIR] Aşama 5 (yarı otomatik) eşiği karşılanıyor: yeterli örneklem "
            f"(>={MIN_POSITIONS_FOR_CONFIDENCE}), BTC-hold'u geçiyor ve girişler rastgeleden anlamlı şekilde iyi "
            f"(p<{ASAMA5_EDGE_P_VALUE}). Bu otomatik onay değil, yalnızca bir ölçüm -- karar hâlâ kullanıcının."
        )
    else:
        if scorecard["insufficient_data"]:
            reason = "yetersiz örneklem"
        elif not scorecard["beats_btc_hold"]:
            reason = "BTC-hold'u geçmiyor"
        elif edge_test is None:
            reason = "rastgele giriş karşılaştırması yapılamadı"
        else:
            reason = f"girişler rastgele girişlerden anlamlı şekilde iyi değil (p={edge_test['p_value']:.3f})"
        lines.append(f"[HENÜZ HAZIR DEĞİL] Aşama 5 eşiği karşılanmıyor ({reason}).")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="whale-tracker Aşama 4 -- paper trading değerlendirmesi")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    args = parser.parse_args()
    with Storage(args.db) as db:
        scorecard = evaluate_paper_trading(db)
    print(render_evaluation_report(scorecard))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
