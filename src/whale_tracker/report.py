"""Plain-text observer report. No signal/decision logic -- Kademe 0 only
(see README.md: "işlem mantığı yok, sinyal birleştirme yok")."""

from __future__ import annotations

from typing import Any


def render_report(
    *,
    onchain_events: list[dict[str, Any]],
    market_snapshot: dict[str, Any] | None,
    sentiment_snapshot: dict[str, Any] | None,
    headlines: list[dict[str, Any]] | None = None,
) -> str:
    lines = ["=== whale-tracker gözlemci raporu ===", ""]

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
        for event in onchain_events:
            tags = []
            if event.get("from_known_exchange"):
                tags.append(f"from={event['from_known_exchange']}")
            if event.get("to_known_exchange"):
                tags.append(f"to={event['to_known_exchange']}")
            tag_str = f" [{', '.join(tags)}]" if tags else " [bilinmeyen cüzdanlar]"
            lines.append(
                f"  blok {event['block_number']}: {event['token']} "
                f"${event['amount_usd_estimate']:,.0f}{tag_str}"
            )
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
