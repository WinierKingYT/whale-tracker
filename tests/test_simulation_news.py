from whale_tracker.signal import _NEGATIVE_NEWS_KEYWORDS
from whale_tracker.simulation.news import NewsSimulator


def _without_timestamps(headlines: list[dict]) -> list[dict]:
    return [{k: v for k, v in h.items() if k != "observed_at"} for h in headlines]


def test_seeded_run_is_reproducible():
    # observed_at is real wall-clock time, excluded from comparison --
    # every RNG-driven field (title, link, ...) must still match exactly.
    sim_a = NewsSimulator(seed=42)
    sim_b = NewsSimulator(seed=42)
    headlines_a = [_without_timestamps(sim_a.tick_headlines()) for _ in range(50)]
    headlines_b = [_without_timestamps(sim_b.tick_headlines()) for _ in range(50)]
    assert headlines_a == headlines_b


def test_headline_shape_matches_real_source_contract():
    sim = NewsSimulator(seed=1)
    headlines = []
    for _ in range(20):
        headlines.extend(sim.tick_headlines())
    assert headlines
    headline = headlines[0]
    assert set(headline.keys()) == {"source", "title", "link", "published_at", "observed_at"}
    assert headline["source"] == "sim"


def test_links_are_unique():
    sim = NewsSimulator(seed=2)
    links = [h["link"] for _ in range(100) for h in sim.tick_headlines()]
    assert len(links) == len(set(links))


def test_negative_keyword_headlines_appear_over_many_cycles():
    """signal.py's _score_sentiment/negative-news path only fires if a
    headline actually contains one of its own keywords -- prove the
    simulator's "negative" templates really do, word-boundary and all."""
    sim = NewsSimulator(seed=3)
    titles = [h["title"].lower() for _ in range(500) for h in sim.tick_headlines()]
    assert any(
        any(__import__("re").search(rf"\b{keyword}\b", title) for keyword in _NEGATIVE_NEWS_KEYWORDS)
        for title in titles
    )
