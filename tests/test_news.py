"""Offline unit tests: mock the HTTP layer, no real network calls."""

from whale_tracker.sources import _retry, news

_SAMPLE_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
<item><title>Bitcoin hits new high</title><link>https://example.com/1</link><pubDate>Wed, 23 Sep 2026 10:00:00 GMT</pubDate></item>
<item><title>Ethereum upgrade ships</title><link>https://example.com/2</link><pubDate>Wed, 23 Sep 2026 09:00:00 GMT</pubDate></item>
</channel></rss>"""


class _FakeResponse:
    def __init__(self, content: bytes, status: int = 200) -> None:
        self.content = content
        self.status_code = status

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError("bad status")


def test_fetch_headlines_parses_and_tags_source(monkeypatch):
    def fake_get(url, headers=None, timeout=None):
        return _FakeResponse(_SAMPLE_RSS.encode("utf-8"))

    monkeypatch.setattr(news.requests, "get", fake_get)

    headlines = news.fetch_headlines(per_feed_limit=10)
    # one entry per (feed, item) -- 2 feeds configured x 2 items each
    assert len(headlines) == 2 * len(news.FEEDS)
    assert headlines[0]["title"] == "Bitcoin hits new high"
    assert headlines[0]["source"] in {name for name, _ in news.FEEDS}


def test_a_single_broken_feed_does_not_fail_the_others(monkeypatch):
    monkeypatch.setattr(_retry.time, "sleep", lambda *a: None)  # skip real backoff delay
    calls = {"n": 0}

    def fake_get(url, headers=None, timeout=None):
        calls["n"] += 1
        if calls["n"] <= _retry.DEFAULT_RETRIES:  # every retry of the first feed fails
            raise news.requests.RequestException("network down")
        return _FakeResponse(_SAMPLE_RSS.encode("utf-8"))

    monkeypatch.setattr(news.requests, "get", fake_get)

    headlines = news.fetch_headlines(per_feed_limit=10)
    assert len(headlines) == 2  # only the second (working) feed's items
