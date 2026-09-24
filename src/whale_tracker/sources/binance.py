"""Binance USDⓈ-M Futures public market data. No API key required --
these are public market-data endpoints, verified free during research
(see docs/DATA-SOURCES.md)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import requests

from ._retry import get_with_retries

BASE_URL = "https://fapi.binance.com"
_TIMEOUT_S = 15


class BinanceMarketDataError(RuntimeError):
    """Raised when Binance's public API returns an unexpected shape or fails."""


def _get(path: str, params: dict[str, Any]) -> Any:
    def _do_request() -> requests.Response:
        response = requests.get(f"{BASE_URL}{path}", params=params, timeout=_TIMEOUT_S)
        response.raise_for_status()
        return response

    try:
        return get_with_retries(_do_request).json()
    except requests.RequestException as error:
        raise BinanceMarketDataError(f"Binance request failed: {path}") from error


def fetch_market_snapshot(symbol: str = "BTCUSDT") -> dict[str, Any]:
    """One combined snapshot: funding rate, open interest, mark price.

    Three separate public endpoints, called together so storage.py's
    market_snapshots row represents "what we knew about `symbol` at this
    moment," not three independently-timestamped facts.
    """
    premium_index = _get("/fapi/v1/premiumIndex", {"symbol": symbol})
    if not isinstance(premium_index, dict) or "lastFundingRate" not in premium_index:
        raise BinanceMarketDataError(f"Unexpected premiumIndex response for {symbol}: {premium_index}")

    open_interest = _get("/fapi/v1/openInterest", {"symbol": symbol})
    if not isinstance(open_interest, dict) or "openInterest" not in open_interest:
        raise BinanceMarketDataError(f"Unexpected openInterest response for {symbol}: {open_interest}")

    return {
        "symbol": symbol,
        "funding_rate": float(premium_index["lastFundingRate"]),
        "open_interest": float(open_interest["openInterest"]),
        "mark_price": float(premium_index["markPrice"]),
        "observed_at": datetime.now(UTC).isoformat(),
    }
