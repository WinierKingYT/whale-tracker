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
- The BTC-hold comparison uses the first position's own entry_price and
  the last closed position's own exit_price as the period's start/end BTC
  price -- real prices actually observed, not a separate lookup, but only
  as good as "first position opened" to "last position closed" being a
  fair window (a first-pass proxy for "same period", not a fixed-calendar
  window)."""

from __future__ import annotations

import argparse
import statistics
from pathlib import Path
from typing import Any

from whale_tracker.paper_trading import VIRTUAL_CAPITAL_USD
from whale_tracker.storage import Storage

DEFAULT_DB_PATH = Path(__file__).resolve().parents[2] / "data" / "whale_tracker.db"

# Plan says "birkac hafta sonuclar olculur" -- a count-based floor as a
# simple, first-pass proxy for "enough trades to mean anything," not a
# statistically derived threshold. Below this, numbers are still shown
# but flagged low-confidence rather than withheld.
MIN_POSITIONS_FOR_CONFIDENCE = 10


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
            "insufficient_data": True,
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
    btc_start_price = first_position["entry_price"]
    btc_end_price = closed[-1]["exit_price"]
    btc_hold_return_pct = (btc_end_price - btc_start_price) / btc_start_price

    return {
        "closed_position_count": len(closed),
        "open_position_count": open_count,
        "insufficient_data": len(closed) < MIN_POSITIONS_FOR_CONFIDENCE,
        "win_rate": round(win_rate, 4),
        "avg_win_pct": round(avg_win_pct, 4) if avg_win_pct is not None else None,
        "avg_loss_pct": round(avg_loss_pct, 4) if avg_loss_pct is not None else None,
        "win_loss_ratio": round(win_loss_ratio, 3) if win_loss_ratio is not None else None,
        "total_pnl_usd": total_pnl_usd,
        "strategy_return_pct": round(strategy_return_pct, 4),
        "max_drawdown_pct": round(max_drawdown_pct, 4),
        "btc_hold_return_pct": round(btc_hold_return_pct, 4),
        "beats_btc_hold": strategy_return_pct > btc_hold_return_pct,
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
    lines.append(f"Aynı dönemde BTC-hold getirisi: {scorecard['btc_hold_return_pct']:+.2%}")
    verdict = "EVET" if scorecard["beats_btc_hold"] else "HAYIR"
    lines.append(f"BTC-hold'u geçiyor mu: {verdict}")
    if not scorecard["beats_btc_hold"]:
        lines.append("  -> PROJECT-PLAN.md section 9: 'sadece BTC tutmak' yeniyorsa gerçek parayı artırmayız.")
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
