"""Alternative.me Fear & Greed Index. Free, no API key -- verified during
research (see docs/DATA-SOURCES.md)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import requests

from ._retry import get_with_retries

URL = "https://api.alternative.me/fng/"
_TIMEOUT_S = 15


class FearGreedError(RuntimeError):
    """Raised when the Fear & Greed API returns an unexpected shape or fails."""


def fetch_fear_greed() -> dict[str, Any]:
    def _do_request() -> requests.Response:
        response = requests.get(URL, params={"limit": 1}, timeout=_TIMEOUT_S)
        response.raise_for_status()
        return response

    try:
        payload = get_with_retries(_do_request).json()
    except requests.RequestException as error:
        raise FearGreedError("Fear & Greed request failed") from error

    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, list) or not data:
        raise FearGreedError(f"Unexpected Fear & Greed response shape: {payload}")

    entry = data[0]
    if "value" not in entry or "value_classification" not in entry:
        raise FearGreedError(f"Unexpected Fear & Greed entry shape: {entry}")

    return {
        "source": "fear_greed",
        "value": float(entry["value"]),
        "label": str(entry["value_classification"]),
        "raw_json": entry,
        "observed_at": datetime.now(UTC).isoformat(),
    }
