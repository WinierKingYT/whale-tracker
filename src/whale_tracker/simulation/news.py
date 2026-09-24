"""Synthetic headline generator -- template-based placeholder text, not
real news. Occasionally injects a headline containing one of signal.py's
own _NEGATIVE_NEWS_KEYWORDS so that corroboration path gets exercised in
simulation exactly as it would against real CoinDesk/Cointelegraph
headlines, not skipped for lack of test data."""

from __future__ import annotations

import random
from datetime import UTC, datetime
from typing import Any

_NEUTRAL_TEMPLATES = (
    "Market analysts weigh in on {asset} price action",
    "{asset} trading volume steady amid mixed signals",
    "Institutional interest in {asset} continues to grow",
    "New {asset} ETF filing submitted to regulators",
    "{asset} network activity hits new monthly high",
)
# Each contains at least one of signal.py's _NEGATIVE_NEWS_KEYWORDS
# ("hacked", "ban", "insolvent", "phishing", "scam", ...) -- "hacked," not
# bare "hack," which signal.py stopped matching after it false-positived
# on a real headline naming "Hack VC" (a firm, not an incident).
_NEGATIVE_TEMPLATES = (
    "Exchange hacked, {asset} withdrawals frozen",
    "Regulators move to ban {asset}-linked exchange",
    "Major {asset} custody firm faces insolvent balance sheet",
    "Phishing scam drains millions in {asset} from users",
)
_ASSETS = ("Bitcoin", "Ethereum", "crypto")
# Calibrated against this project's own real observer.log this session:
# two real RSS feeds (CoinDesk+Cointelegraph) polled every 15 min mostly
# logged "0 yeni başlık," occasionally 1 -- not "a new headline every
# other cycle." The first version of this simulator used 0.5, which (via
# signal.py's _has_recent_negative_news reading a fixed 30-row window,
# not a time window) kept a negative headline "recent" for roughly 60
# simulated cycles at a time -- effectively always-on, permanently
# zeroing accumulation candidates' onchain_flow component (see
# _NEGATIVE_NEWS penalty in signal.py, direction-specific) while leaving
# distribution candidates unpenalized. That asymmetry showed up as
# accumulation candidates almost never reaching "strong" in a 1000-cycle
# run while distribution did constantly -- a simulator calibration bug,
# not a signal.py bug (found by actually running the simulation, not by
# reasoning about it in the abstract).
_HEADLINE_PROBABILITY = 0.15
_NEGATIVE_PROBABILITY = 0.08


class NewsSimulator:
    def __init__(self, *, seed: int | None = None) -> None:
        self._rng = random.Random(seed)
        self._counter = 0

    def tick_headlines(self, *, max_per_cycle: int = 1, observed_at: str | None = None) -> list[dict[str, Any]]:
        headlines: list[dict[str, Any]] = []
        for _ in range(max_per_cycle):
            if self._rng.random() > _HEADLINE_PROBABILITY:
                continue
            self._counter += 1
            asset = self._rng.choice(_ASSETS)
            is_negative = self._rng.random() < _NEGATIVE_PROBABILITY
            template = self._rng.choice(_NEGATIVE_TEMPLATES if is_negative else _NEUTRAL_TEMPLATES)
            headlines.append({
                "source": "sim",
                "title": template.format(asset=asset),
                "link": f"https://sim.example/{self._counter}",
                "published_at": None,
                "observed_at": observed_at or datetime.now(UTC).isoformat(),
            })
        return headlines
