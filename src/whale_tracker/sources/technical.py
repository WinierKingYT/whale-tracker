"""Teknik piyasa yapısı (PROJECT-PLAN.md section 3D): trend, destek/
direnç, volatilite. Uses Binance's public daily klines (candlesticks) --
same free, keyless API as sources/binance.py, verified working directly
against the real endpoint during development.

Deliberately simple and transparent, not a technical-analysis library:
support/resistance are the recent swing low/high over a lookback window
(a standard, well-known heuristic -- not fitted pivot points or fancy
indicators), trend is price vs. a simple moving average, volatility is
the stddev of daily returns. Every number here is explainable in one
sentence; that matters more at this stage than sophistication, since the
whole point is to remove signal.py's "structurally absent" gap honestly,
not to replace it with an opaque one."""

from __future__ import annotations

import statistics
from datetime import UTC, datetime
from typing import Any

import requests

BASE_URL = "https://fapi.binance.com"
_TIMEOUT_S = 15

DEFAULT_LOOKBACK_DAYS = 30
SUPPORT_PROXIMITY_PCT = 0.03  # within 3% of support counts as "near/above support"


class TechnicalDataError(RuntimeError):
    """Raised when the klines request fails or returns an unexpected shape."""


def _fetch_daily_klines(symbol: str, *, limit: int) -> list[list[Any]]:
    try:
        response = requests.get(
            f"{BASE_URL}/fapi/v1/klines",
            params={"symbol": symbol, "interval": "1d", "limit": limit},
            timeout=_TIMEOUT_S,
        )
        response.raise_for_status()
        data = response.json()
    except requests.RequestException as error:
        raise TechnicalDataError(f"Klines request failed: {symbol}") from error
    if not isinstance(data, list) or not data:
        raise TechnicalDataError(f"Unexpected klines response for {symbol}: {data}")
    return data


def compute_technical_snapshot(symbol: str, klines: list[list[Any]], *, lookback_days: int) -> dict[str, Any]:
    """Pure computation over daily klines -- no network I/O. Split out of
    fetch_technical_snapshot() so simulation/market.py can run the exact
    same support/resistance/trend logic against synthetic candles instead
    of a parallel reimplementation that could silently drift from the
    real thing. `klines` is Binance's raw kline shape: a list of
    [open_time, open, high, low, close, ...] rows, oldest first."""
    highs = [float(candle[2]) for candle in klines]
    lows = [float(candle[3]) for candle in klines]
    closes = [float(candle[4]) for candle in klines]

    current_price = closes[-1]
    support = min(lows)
    resistance = max(highs)
    sma = sum(closes) / len(closes)

    if current_price > sma * 1.01:
        trend = "yükseliş"
    elif current_price < sma * 0.99:
        trend = "düşüş"
    else:
        trend = "yatay"

    daily_returns = [
        (closes[i] - closes[i - 1]) / closes[i - 1] for i in range(1, len(closes))
    ]
    volatility = statistics.pstdev(daily_returns) if len(daily_returns) > 1 else 0.0

    # "distance_to_support_pct" is signed: positive = price is that far
    # above support, negative = price has broken below it. Same for
    # resistance, mirrored: positive = that far BELOW resistance.
    distance_to_support_pct = (current_price - support) / support if support else float("inf")
    is_above_support = current_price >= support
    is_near_support = 0 <= distance_to_support_pct <= SUPPORT_PROXIMITY_PCT

    distance_to_resistance_pct = (resistance - current_price) / resistance if resistance else float("inf")
    is_near_resistance = 0 <= distance_to_resistance_pct <= SUPPORT_PROXIMITY_PCT

    return {
        "symbol": symbol,
        "lookback_days": lookback_days,
        "current_price": current_price,
        "support": support,
        "resistance": resistance,
        "sma": sma,
        "trend": trend,
        "volatility_daily_stddev": volatility,
        "distance_to_support_pct": distance_to_support_pct,
        "is_above_support": is_above_support,
        "is_near_support": is_near_support,
        "distance_to_resistance_pct": distance_to_resistance_pct,
        "is_near_resistance": is_near_resistance,
        "observed_at": datetime.now(UTC).isoformat(),
    }


def fetch_technical_snapshot(symbol: str = "BTCUSDT", *, lookback_days: int = DEFAULT_LOOKBACK_DAYS) -> dict[str, Any]:
    klines = _fetch_daily_klines(symbol, limit=lookback_days)
    return compute_technical_snapshot(symbol, klines, lookback_days=lookback_days)
