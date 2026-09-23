"""Sinyal üretici (Aşama 2): corroborate multiple signals into a scored
candidate, per PROJECT-PLAN.md section 4 -- "Karar tek bir sinyalle değil,
sinyallerin birbirini doğrulamasıyla verilir."

Still no trading. This module only produces and stores named candidates
with their component scores and a plain-language rationale -- nothing
here places, sizes, or approves a trade. That boundary is enforced by
what this module does NOT import (no exchange trading API) and by
README.md's own "Kritik sınır" section.

Technical corroboration (section D -- trend/destek/direnç) now comes from
sources/technical.py's stored snapshot, added deliberately after the
first version shipped without it (build order mattered more than
completeness on day one -- see README.md's status history). If no
technical snapshot exists yet (observe.py hasn't fetched one), this
module falls back to the old capped-confidence behavior rather than
silently treating the missing signal as neutral/favorable.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from typing import Any

# Funding rate is per-8h on Binance. These bands are a first-pass estimate
# from general market research (0.01%/8h cited as a commonly-referenced
# "neutral" level), not calibrated against this project's own historical
# data yet -- revisit once real observer history accumulates, same as the
# onchain min_usd threshold in docs/TECHNICAL-APPROACH.md.
FUNDING_NEUTRAL_BAND = 0.0001  # ±0.01%
FUNDING_HIGH_THRESHOLD = 0.0005  # 0.05%
FUNDING_LOW_THRESHOLD = -0.0002  # -0.02%

_NEGATIVE_NEWS_KEYWORDS = (
    "hack", "exploit", "hacked", "stolen", "theft", "lawsuit", "sec charges",
    "ban", "crackdown", "delist", "insolvent", "bankruptcy", "collapse",
    "phishing", "scam", "rug pull",
)

# Used only as a fallback cap when no technical snapshot exists yet (see
# generate_candidates) -- normally superseded by the real technical component.
_MAX_CONFIDENCE_WITHOUT_TECHNICAL = 0.75


def _score_technical(technical: dict[str, Any] | None, direction: str) -> tuple[float, str]:
    """Score how much the technical picture corroborates `direction`.
    Weight (0.25) matches onchain_flow's 0.4 + funding's 0.25 + sentiment's
    0.15 scale -- technical is a real, not token, contributor now."""
    if technical is None:
        return 0.0, "UYARI: teknik anlık görüntü henüz yok (ilk çalıştırma?) -- bu bileşen eksik"

    trend = technical["trend"]
    if direction == "accumulation":
        if not technical["is_above_support"]:
            return 0.0, f"fiyat ${technical['support']:,.0f} desteğinin ALTINDA -- birikim tezini zayıflatıyor"
        score = 0.15 if trend != "düşüş" else 0.05
        detail = f"fiyat ${technical['support']:,.0f} desteğinin üstünde (trend: {trend})"
        if technical["is_near_support"]:
            score += 0.10
            detail += ", desteğe yakın -- klasik giriş bölgesi"
        return score, detail
    else:  # distribution
        score = 0.15 if trend != "yükseliş" else 0.05
        detail = f"trend: {trend}"
        if technical["is_near_resistance"]:
            score += 0.10
            detail += f", ${technical['resistance']:,.0f} direncine yakın -- klasik dağıtım bölgesi"
        return score, detail


def _aggregate_exchange_flow(storage: Any, *, hours: int) -> dict[str, float]:
    """Net stablecoin flow into/out of KNOWN exchange wallets over the
    window. Positive net_inflow_usd = more moved INTO exchanges (possible
    sell pressure); negative = net outflow (possible accumulation).
    Deliberately excludes dex/flagged/unknown -- only wallets tagged with
    a plain exchange name (not "DEX:"/"⚠ FLAGGED:") count toward this."""
    cutoff = (datetime.now(UTC) - timedelta(hours=hours)).isoformat()
    events = storage.recent_onchain_events(limit=5000)
    inflow = 0.0
    outflow = 0.0
    for event in events:
        if event["observed_at"] < cutoff:
            continue
        to_tag = event.get("to_known_exchange") or ""
        from_tag = event.get("from_known_exchange") or ""
        if to_tag and not to_tag.startswith(("DEX:", "⚠")):
            inflow += event["amount_usd_estimate"]
        if from_tag and not from_tag.startswith(("DEX:", "⚠")):
            outflow += event["amount_usd_estimate"]
    return {"inflow_usd": inflow, "outflow_usd": outflow, "net_inflow_usd": inflow - outflow}


def _classify_funding(rate: float) -> str:
    if rate >= FUNDING_HIGH_THRESHOLD:
        return "high"
    if rate <= FUNDING_LOW_THRESHOLD:
        return "low"
    return "neutral"


def _has_recent_negative_news(headlines: list[dict[str, Any]]) -> tuple[bool, str | None]:
    for headline in headlines:
        title_lower = headline["title"].lower()
        for keyword in _NEGATIVE_NEWS_KEYWORDS:
            if re.search(rf"\b{re.escape(keyword)}\b", title_lower):
                return True, headline["title"]
    return False, None


def generate_candidates(storage: Any, *, flow_window_hours: int = 24) -> list[dict[str, Any]]:
    """Return a list of at most one candidate per direction (accumulation/
    distribution), each with its component scores and rationale. Returns
    an empty list when corroboration is weak or data is missing -- this
    is the expected, common case, not an error."""
    flow = _aggregate_exchange_flow(storage, hours=flow_window_hours)
    market = storage.latest_market_snapshot("BTCUSDT")
    sentiment = storage.latest_sentiment_snapshot("fear_greed")
    technical = storage.latest_technical_snapshot("BTCUSDT")
    negative_news, negative_headline = _has_recent_negative_news(storage.recent_headlines(limit=30))

    if market is None:
        return []  # can't corroborate anything without at least market state

    funding_class = _classify_funding(market["funding_rate"])
    candidates: list[dict[str, Any]] = []

    for direction, flow_signal in (
        ("accumulation", flow["net_inflow_usd"] < 0),
        ("distribution", flow["net_inflow_usd"] > 0),
    ):
        if not flow_signal or flow["inflow_usd"] + flow["outflow_usd"] == 0:
            continue

        components: dict[str, float] = {}
        rationale: list[str] = []

        components["onchain_flow"] = min(abs(flow["net_inflow_usd"]) / 10_000_000, 1.0) * 0.4
        rationale.append(
            f"{flow_window_hours}s net borsa akışı: "
            f"{'çıkış' if direction == 'accumulation' else 'giriş'} "
            f"${abs(flow['net_inflow_usd']):,.0f}"
        )

        if funding_class == "neutral":
            components["funding"] = 0.25
            rationale.append(f"funding nötr ({market['funding_rate']:.4%}) -- aşırı kaldıraçlı taraf yok")
        elif (direction == "accumulation" and funding_class == "low") or (
            direction == "distribution" and funding_class == "high"
        ):
            components["funding"] = 0.1
            rationale.append(f"funding {funding_class} ({market['funding_rate']:.4%}) -- yönle tutarlı ama aşırı")
        else:
            components["funding"] = 0.0
            rationale.append(f"funding {funding_class} ({market['funding_rate']:.4%}) -- yönle çelişiyor, zayıflatıcı")

        if sentiment:
            components["sentiment"] = 0.15
            rationale.append(f"Fear&Greed: {sentiment['value']:.0f} ({sentiment['label']})")

        if negative_news and direction == "accumulation":
            # Per PROJECT-PLAN.md's own worked example: accumulation +
            # negative news present is explicitly the counter-case, not a
            # buy candidate -- zero out onchain_flow's contribution rather
            # than just capping the total, so this shows up clearly in
            # the component breakdown, not just a smaller final number.
            components["onchain_flow"] = 0.0
            rationale.append(f"olumsuz haber var, zayıflatıcı: \"{negative_headline}\"")
        elif negative_news:
            rationale.append(f"olumsuz haber var (dağıtım yönüyle çelişmiyor): \"{negative_headline}\"")
        else:
            rationale.append("son başlıklarda olumsuz haber tespit edilmedi")

        technical_score, technical_detail = _score_technical(technical, direction)
        components["technical"] = technical_score
        rationale.append(technical_detail)

        confidence = sum(components.values())
        if technical is None:
            # No real technical component this run -- keep the old
            # honesty cap rather than let the other three alone imply
            # more confidence than was actually checked.
            confidence = min(confidence, _MAX_CONFIDENCE_WITHOUT_TECHNICAL)
        candidates.append({
            "direction": direction,
            "confidence": round(min(confidence, 1.0), 3),
            "components": components,
            "rationale": rationale,
            "flow": flow,
            "technical_available": technical is not None,
            "generated_at": datetime.now(UTC).isoformat(),
        })

    return candidates
