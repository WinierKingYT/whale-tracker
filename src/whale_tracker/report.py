"""Plain-text observer report. No signal/decision logic -- Kademe 0 only
(see README.md: "işlem mantığı yok, sinyal birleştirme yok").

Events are grouped, not just listed in arrival order, because
sources/onchain.py's wide-net scan mixes very different kinds of things
together: real exchange/fund flow, DEX routing noise (see
data/known-exchange-wallets.json's "dex_infrastructure" -- NOT whale
signal), flagged addresses, and genuinely unlabeled wallets. Grouping is
presentation only -- it does not filter, score, or decide anything."""

from __future__ import annotations

from typing import Any

from whale_tracker.flow import side_entity_type
from whale_tracker.sources.onchain import ENTITY_DEX, ENTITY_FLAGGED, load_wallet_registry


def _classify(event: dict[str, Any]) -> str:
    registry = load_wallet_registry()
    kinds = {side_entity_type(event, side, registry) for side in ("from", "to")}
    if ENTITY_FLAGGED in kinds:
        return "flagged"
    if ENTITY_DEX in kinds:
        return "dex"
    if kinds - {None}:
        return "known"
    return "unknown"


def _format_event(event: dict[str, Any]) -> str:
    tags = []
    if event.get("from_known_exchange"):
        tags.append(f"from={event['from_known_exchange']}")
    if event.get("to_known_exchange"):
        tags.append(f"to={event['to_known_exchange']}")
    tag_str = f" [{', '.join(tags)}]" if tags else ""
    line = f"  blok {event['block_number']}: {event['token']} ${event['amount_usd_estimate']:,.0f}{tag_str}"
    classification = event.get("classification")
    if classification:
        line += (
            f"\n    → Kademe 1 [{classification['significance']}, "
            f"güven={classification['confidence']:.2f}]: {classification['interpretation']}"
        )
    return line


def render_report(
    *,
    onchain_events: list[dict[str, Any]],
    market_snapshot: dict[str, Any] | None = None,
    market_snapshots: dict[str, dict[str, Any] | None] | None = None,
    sentiment_snapshot: dict[str, Any] | None = None,
    headlines: list[dict[str, Any]] | None = None,
    signal_candidates: list[dict[str, Any]] | None = None,
    closed_positions: list[dict[str, Any]] | None = None,
    abstentions: dict[str, list[str]] | None = None,
) -> str:
    # `market_snapshot` (singular) stays as a BTCUSDT-only convenience for
    # single-symbol callers/tests; `market_snapshots` (plural, symbol ->
    # snapshot) is what observe.py passes now that ETH is also tracked.
    if market_snapshots is None:
        market_snapshots = {"BTCUSDT": market_snapshot} if market_snapshot is not None else {}

    lines = ["=== whale-tracker gözlemci raporu ===", ""]

    abstaining = {symbol: reasons for symbol, reasons in (abstentions or {}).items() if reasons}
    if abstaining:
        lines.append("ABSTAIN (karar verilmedi -- aday, analiz, pozisyon, onay yok):")
        for symbol, reasons in abstaining.items():
            lines.append(f"  [{symbol}] {'; '.join(reasons)}")
        lines.append("")
    signal_candidates = signal_candidates or []
    if signal_candidates:
        lines.append("Sinyal adayları (henüz işlem değil, öneri + gerekçe):")
        for candidate in signal_candidates:
            cap_note = "" if candidate.get("technical_available", True) else " (teknik sinyal eksik, tavanlı)"
            symbol = candidate.get("symbol", "BTCUSDT")
            lines.append(f"  [{symbol}/{candidate['direction']}] güven={candidate['confidence']:.2f}{cap_note}")
            for line in candidate["rationale"]:
                lines.append(f"    - {line}")
            analysis = candidate.get("deep_analysis")
            if analysis:
                lines.append(f"    → Kademe 2 [{analysis['corroboration_strength']}]: {analysis['assessment']}")
                lines.append(f"      karşı senaryo: {analysis['counter_argument']}")
                if analysis["risk_flags"]:
                    lines.append(f"      risk: {', '.join(analysis['risk_flags'])}")
            proposal = candidate.get("final_proposal")
            if proposal:
                if proposal["action"] == "no_action":
                    lines.append(f"    → Kademe 3: işlem yok -- {proposal['reason']}")
                else:
                    lines.append(
                        f"    → Kademe 3 [kağıt üzerinde, kanaat={proposal['conviction']}]: "
                        f"{proposal['entry_rationale']}"
                    )
                    lines.append(
                        f"      stop-loss=${proposal['stop_loss_price']:,.0f}, "
                        f"hesap riski=%{proposal['max_position_size_pct']*100:.0f}"
                    )
                    lines.append(f"      en kötü senaryo: {proposal['worst_case_scenario']}")
                    for counter in proposal["counter_arguments"]:
                        lines.append(f"      karşı argüman: {counter}")
            position = candidate.get("paper_position")
            if position:
                lines.append(
                    f"      → Aşama 3 kağıt pozisyon açıldı: giriş=${position['entry_price']:,.0f}, "
                    f"stop=${position['stop_loss_price']:,.0f}, hedef=${position['take_profit_price']:,.0f}, "
                    f"büyüklük=${position['position_size_usd']:,.0f}"
                )
        lines.append("")

    closed_positions = closed_positions or []
    if closed_positions:
        lines.append("Kapanan kağıt pozisyonlar (bu turda):")
        for position in closed_positions:
            symbol = position.get("symbol", "BTCUSDT")
            lines.append(
                f"  [{symbol}/{position['status']}] giriş=${position['entry_price']:,.0f} → "
                f"çıkış=${position['exit_price']:,.0f}, P&L=${position['pnl_usd']:,.2f} "
                f"({position['pnl_pct']:+.2%})"
            )
        lines.append("")

    lines.append("Piyasa:")
    if market_snapshots:
        for symbol in sorted(market_snapshots):
            snapshot = market_snapshots[symbol]
            lines.append(f"  {symbol}:")
            if snapshot:
                lines.append(f"    mark price: ${snapshot['mark_price']:,.2f}")
                lines.append(f"    funding rate: {snapshot['funding_rate']:.5%}")
                lines.append(f"    open interest: {snapshot['open_interest']:,.2f}")
            else:
                lines.append("    (veri yok)")
    else:
        lines.append("  (veri yok)")
    lines.append("")

    lines.append("Duygu durumu:")
    if sentiment_snapshot:
        lines.append(f"  Fear & Greed: {sentiment_snapshot['value']:.0f} ({sentiment_snapshot['label']})")
    else:
        lines.append("  (veri yok)")
    lines.append("")

    lines.append(f"Zincir üstü büyük transferler ({len(onchain_events)} yeni):")
    if onchain_events:
        groups: dict[str, list[dict[str, Any]]] = {"flagged": [], "known": [], "unknown": [], "dex": []}
        for event in onchain_events:
            groups[_classify(event)].append(event)

        if groups["flagged"]:
            lines.append(f"  ⚠ İşaretlenmiş ({len(groups['flagged'])}):")
            for event in groups["flagged"]:
                lines.append(_format_event(event))
        if groups["known"]:
            lines.append(f"  Bilinen borsa/kurum ({len(groups['known'])}):")
            for event in groups["known"]:
                lines.append(_format_event(event))
        if groups["unknown"]:
            lines.append(f"  Bilinmeyen cüzdanlar ({len(groups['unknown'])}):")
            for event in groups["unknown"]:
                lines.append(_format_event(event))
        if groups["dex"]:
            # DEX routing noise, not whale signal -- summarized, not
            # itemized, so it doesn't drown out the categories above.
            dex_total = sum(e["amount_usd_estimate"] for e in groups["dex"])
            lines.append(f"  DEX rutin trafiği (gürültü, özetlendi): {len(groups['dex'])} işlem, ${dex_total:,.0f}")
    else:
        lines.append("  (bu turda eşik-üstü transfer yok)")
    lines.append("")

    headlines = headlines or []
    lines.append(f"Haberler ({len(headlines)} yeni başlık):")
    if headlines:
        for headline in headlines:
            lines.append(f"  [{headline['source']}] {headline['title']}")
    else:
        lines.append("  (bu turda yeni başlık yok)")

    return "\n".join(lines)
