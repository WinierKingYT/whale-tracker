from datetime import UTC, datetime

from whale_tracker import simulate
from whale_tracker.observe import TRACKED_SYMBOLS
from whale_tracker.simulation.market import MarketSimulator
from whale_tracker.simulation.news import NewsSimulator
from whale_tracker.simulation.onchain import OnchainSimulator
from whale_tracker.simulation.sentiment import SentimentSimulator
from whale_tracker.storage import Storage


def _fresh_simulators(seed: int):
    markets = {symbol: MarketSimulator(symbol, seed=seed) for symbol in TRACKED_SYMBOLS}
    return markets, OnchainSimulator(seed=seed), SentimentSimulator(seed=seed), NewsSimulator(seed=seed)


def test_run_cycle_without_ai_populates_market_and_technical_snapshots(tmp_path):
    with Storage(tmp_path / "t.db") as db:
        markets, onchain_sim, sentiment_sim, news_sim = _fresh_simulators(seed=1)
        simulate.run_cycle(db, markets, onchain_sim, sentiment_sim, news_sim, with_ai=False)

        for symbol in TRACKED_SYMBOLS:
            assert db.latest_market_snapshot(symbol) is not None
            assert db.latest_technical_snapshot(symbol) is not None
        assert db.latest_sentiment_snapshot("fear_greed") is not None


def test_many_cycles_without_ai_never_call_real_ai_and_stay_offline(tmp_path, monkeypatch):
    """The whole point of --with-ai=False: this must never shell out to a
    real Hermes/Claude CLI. Monkeypatch both real entry points to explode
    if called, then run enough cycles that at least one signal candidate
    (and plausibly a strong one) is virtually guaranteed."""
    def boom(*a, **k):
        raise AssertionError("with_ai=False must never call the real AI")

    monkeypatch.setattr(simulate, "generate_deep_analysis", boom)
    monkeypatch.setattr(simulate, "generate_final_proposal", boom)
    monkeypatch.setattr(simulate, "classify_top_events", lambda events, limit: {})

    with Storage(tmp_path / "t.db") as db:
        markets, onchain_sim, sentiment_sim, news_sim = _fresh_simulators(seed=2)
        for _ in range(300):
            simulate.run_cycle(db, markets, onchain_sim, sentiment_sim, news_sim, with_ai=False)

        candidates = db._conn.execute("SELECT COUNT(*) c FROM signal_candidates").fetchone()["c"]
    assert candidates > 0  # 300 cycles across 2 symbols should produce at least some candidates


def test_synthetic_deep_analysis_strength_tracks_mechanical_confidence():
    weak = simulate._synthetic_deep_analysis({"confidence": 0.1})
    moderate = simulate._synthetic_deep_analysis({"confidence": 0.5})
    strong = simulate._synthetic_deep_analysis({"confidence": 0.9})
    assert weak["corroboration_strength"] == "weak"
    assert moderate["corroboration_strength"] == "moderate"
    assert strong["corroboration_strength"] == "strong"
    assert "simülasyon" in weak["assessment"]


def test_synthetic_final_proposal_reuses_real_stop_loss_math():
    from whale_tracker.sources.proposal import _compute_stop_loss

    technical = {"support": 70000.0, "resistance": 75000.0}
    proposal = simulate._synthetic_final_proposal({"direction": "accumulation"}, technical)
    assert proposal["action"] == "long_candidate"
    assert proposal["stop_loss_price"] == _compute_stop_loss(technical)
    assert proposal["max_position_size_pct"] == simulate.MAX_POSITION_SIZE_PCT


def test_synthetic_final_proposal_no_action_for_distribution():
    proposal = simulate._synthetic_final_proposal({"direction": "distribution"}, {"support": 70000.0})
    assert proposal["action"] == "no_action"


def test_synthetic_final_proposal_no_action_without_technical():
    proposal = simulate._synthetic_final_proposal({"direction": "accumulation"}, None)
    assert proposal["action"] == "no_action"


def test_strong_candidate_eventually_opens_a_paper_position(tmp_path, monkeypatch):
    """End-to-end, no AI: run enough cycles that a mechanically-confident
    (>=0.7) accumulation candidate shows up, and confirm it actually
    reaches an open paper position -- the whole point of building this.

    A real mechanically-strong (>=0.7 confidence) candidate turned out to
    be too rare to rely on emerging by chance even over 1000 simulated
    cycles with an elevated onchain event rate (signal.py's real
    corroboration math needs several components near-maxed at once) --
    that would make this test flaky either way it landed. Instead,
    monkeypatch generate_candidates to deterministically hand run_cycle
    one guaranteed-strong accumulation candidate per call, which tests
    exactly the thing this test is actually about: does the synthetic
    Kademe 2/3 stand-in correctly wire a strong candidate through to a
    real, code-computed stop-loss/take-profit paper position."""
    def fake_strong_candidate(storage, *, symbol, flow_window_hours=24, now=None):
        return [{
            "symbol": symbol, "direction": "accumulation", "confidence": 0.95,
            "components": {}, "rationale": ["test"],
            "generated_at": datetime.now(UTC).isoformat(),
        }]

    monkeypatch.setattr(simulate, "generate_candidates", fake_strong_candidate)

    with Storage(tmp_path / "t.db") as db:
        markets, onchain_sim, sentiment_sim, news_sim = _fresh_simulators(seed=123)
        for _ in range(10):
            simulate.run_cycle(db, markets, onchain_sim, sentiment_sim, news_sim, with_ai=False)

        total_positions = db._conn.execute("SELECT COUNT(*) c FROM paper_positions").fetchone()["c"]
    assert total_positions > 0
