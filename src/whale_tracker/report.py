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


def _classify(event: dict[str, Any]) -> str:
    from_tag = event.get("from_known_exchange") or ""
    to_tag = event.get("to_known_exchange") or ""
    if from_tag.startswith("⚠") or to_tag.startswith("⚠"):
        return "flagged"
    if from_tag.startswith("DEX:") or to_tag.startswith("DEX:"):
        return "dex"
    if from_tag or to_tag:
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
    market_snapshot: dict[str, Any] | None,
    sentiment_snapshot: dict[str, Any] | None,
    headlines: list[dict[str, Any]] | None = None,
    signal_candidates: list[dict[str, Any]] | None = None,
) -> str:
    lines = ["=== whale-tracker gözlemci raporu ===", ""]

    signal_candidates = signal_candidates or []
    if signal_candidates:
        lines.append("Sinyal adayları (henüz işlem değil, öneri + gerekçe):")
        for candidate in signal_candidates:
            cap_note = "" if candidate.get("technical_available", True) else " (teknik sinyal eksik, tavanlı)"
            lines.append(f"  [{candidate['direction']}] güven={candidate['confidence']:.2f}{cap_note}")
            for line in candidate["rationale"]:
                lines.append(f"    - {line}")
            analysis = candidate.get("deep_analysis")
            if analysis:
                lines.append(f"    → Kademe 2 [{analysis['corroboration_strength']}]: {analysis['assessment']}")
                lines.append(f"      karşı senaryo: {analysis['counter_argument']}")
                if analysis["risk_flags"]:
                    lines.append(f"      risk: {', '.join(analysis['risk_flags'])}")
        lines.append("")

    lines.append("Piyasa (BTCUSDT):")
    if market_snapshot:
        lines.append(f"  mark price: ${market_snapshot['mark_price']:,.2f}")
        lines.append(f"  funding rate: {market_snapshot['funding_rate']:.5%}")
        lines.append(f"  open interest: {market_snapshot['open_interest']:,.2f} BTC")
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
