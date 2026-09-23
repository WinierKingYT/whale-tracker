"""Crypto news via RSS. Free, no API key -- standard RSS 2.0, parsed with
the stdlib (no extra dependency). Feed URLs verified reachable during
research (see docs/DATA-SOURCES.md)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from xml.etree import ElementTree

import requests

_TIMEOUT_S = 15
_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

FEEDS: tuple[tuple[str, str], ...] = (
    ("coindesk", "https://www.coindesk.com/arc/outboundfeeds/rss/"),
    ("cointelegraph", "https://cointelegraph.com/rss"),
)


class NewsFeedError(RuntimeError):
    """Raised when a feed can't be fetched or parsed."""


def _fetch_feed(url: str) -> list[dict[str, Any]]:
    try:
        response = requests.get(url, headers={"User-Agent": _USER_AGENT}, timeout=_TIMEOUT_S)
        response.raise_for_status()
    except requests.RequestException as error:
        raise NewsFeedError(f"Feed request failed: {url}") from error

    try:
        root = ElementTree.fromstring(response.content)
    except ElementTree.ParseError as error:
        raise NewsFeedError(f"Feed XML parse failed: {url}") from error

    items = []
    for item in root.findall("./channel/item"):
        title = item.findtext("title")
        link = item.findtext("link")
        pub_date = item.findtext("pubDate")
        if title is None or link is None:
            continue
        items.append({"title": title.strip(), "link": link.strip(), "published_at": pub_date})
    return items


def fetch_headlines(*, per_feed_limit: int = 10) -> list[dict[str, Any]]:
    """Fetch recent headlines from every configured feed. A single feed
    failing does not fail the others -- each source is independent, same
    principle as sources/binance.py, sources/sentiment.py, sources/onchain.py."""
    observed_at = datetime.now(UTC).isoformat()
    headlines: list[dict[str, Any]] = []
    for feed_name, url in FEEDS:
        try:
            items = _fetch_feed(url)
        except NewsFeedError:
            continue
        for item in items[:per_feed_limit]:
            headlines.append({**item, "source": feed_name, "observed_at": observed_at})
    return headlines
