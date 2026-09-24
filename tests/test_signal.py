from datetime import UTC, datetime, timedelta

from whale_tracker import signal
from whale_tracker.storage import Storage


def _now_iso(hours_ago: float = 0) -> str:
    return (datetime.now(UTC) - timedelta(hours=hours_ago)).isoformat()


def _seed_outflow_event(db, *, amount, hours_ago=1):
    db.insert_onchain_event({
        "tx_hash": f"0x{hours_ago}-{amount}", "log_index": 0, "block_number": 1, "token": "USDT",
        "from_address": "0xexchange", "to_address": "0xuser", "amount_usd_estimate": amount,
        "raw_amount": "1", "from_known_exchange": "binance", "to_known_exchange": None,
        "observed_at": _now_iso(hours_ago),
    })


def _seed_inflow_event(db, *, amount, hours_ago=1):
    db.insert_onchain_event({
        "tx_hash": f"0xin-{hours_ago}-{amount}", "log_index": 0, "block_number": 1, "token": "USDT",
        "from_address": "0xuser", "to_address": "0xexchange", "amount_usd_estimate": amount,
        "raw_amount": "1", "from_known_exchange": None, "to_known_exchange": "binance",
        "observed_at": _now_iso(hours_ago),
    })


def test_no_market_snapshot_means_no_candidates(tmp_path):
    with Storage(tmp_path / "t.db") as db:
        assert signal.generate_candidates(db) == []


def test_net_outflow_with_neutral_funding_and_no_bad_news_produces_accumulation_candidate(tmp_path):
    with Storage(tmp_path / "t.db") as db:
        db.insert_market_snapshot({
            "symbol": "BTCUSDT", "funding_rate": 0.00005, "open_interest": 100.0,
            "mark_price": 90000.0, "observed_at": _now_iso(),
        })
        db.insert_sentiment_snapshot({
            "source": "fear_greed", "value": 50.0, "label": "Neutral",
            "raw_json": {}, "observed_at": _now_iso(),
        })
        _seed_outflow_event(db, amount=15_000_000)

        candidates = signal.generate_candidates(db)

    directions = {c["direction"] for c in candidates}
    assert "accumulation" in directions
    accumulation = next(c for c in candidates if c["direction"] == "accumulation")
    assert accumulation["confidence"] > 0
    assert accumulation["components"]["technical"] == 0.0
    assert accumulation["confidence"] <= signal._MAX_CONFIDENCE_WITHOUT_TECHNICAL


def test_negative_news_zeroes_out_flow_component_for_accumulation(tmp_path):
    with Storage(tmp_path / "t.db") as db:
        db.insert_market_snapshot({
            "symbol": "BTCUSDT", "funding_rate": 0.00005, "open_interest": 100.0,
            "mark_price": 90000.0, "observed_at": _now_iso(),
        })
        _seed_outflow_event(db, amount=15_000_000)
        db.insert_headline({
            "source": "coindesk", "title": "Major exchange hacked, $200M drained",
            "link": "https://example.com/x", "published_at": None, "observed_at": _now_iso(),
        })

        candidates = signal.generate_candidates(db)

    accumulation = next(c for c in candidates if c["direction"] == "accumulation")
    assert accumulation["components"]["onchain_flow"] == 0.0
    assert any("olumsuz haber" in line for line in accumulation["rationale"])


def test_negative_news_ignores_proper_noun_false_positive(tmp_path):
    """Regression: bare 'hack' used to word-boundary-match 'Hack VC' (a
    venture capital firm's name) in real production headlines, falsely
    zeroing accumulation's onchain_flow for hours. 'hacked' still catches
    a real incident; a name containing 'Hack' must not trigger it."""
    with Storage(tmp_path / "t.db") as db:
        db.insert_market_snapshot({
            "symbol": "BTCUSDT", "funding_rate": 0.00005, "open_interest": 100.0,
            "mark_price": 90000.0, "observed_at": _now_iso(),
        })
        _seed_outflow_event(db, amount=15_000_000)
        db.insert_headline({
            "source": "coindesk", "title": "Former Hack VC partner found dead at 37",
            "link": "https://example.com/y", "published_at": None, "observed_at": _now_iso(),
        })

        candidates = signal.generate_candidates(db)

    accumulation = next(c for c in candidates if c["direction"] == "accumulation")
    assert accumulation["components"]["onchain_flow"] > 0.0


def test_old_events_outside_window_are_excluded(tmp_path):
    with Storage(tmp_path / "t.db") as db:
        db.insert_market_snapshot({
            "symbol": "BTCUSDT", "funding_rate": 0.0, "open_interest": 100.0,
            "mark_price": 90000.0, "observed_at": _now_iso(),
        })
        _seed_outflow_event(db, amount=15_000_000, hours_ago=48)  # outside 24h window

        candidates = signal.generate_candidates(db, flow_window_hours=24)

    assert candidates == []  # no flow signal inside the window -> nothing to corroborate


def test_technical_snapshot_present_contributes_a_real_score_and_lifts_the_cap(tmp_path):
    with Storage(tmp_path / "t.db") as db:
        db.insert_market_snapshot({
            "symbol": "BTCUSDT", "funding_rate": 0.00005, "open_interest": 100.0,
            "mark_price": 90000.0, "observed_at": _now_iso(),
        })
        db.insert_technical_snapshot({
            "symbol": "BTCUSDT", "current_price": 90000.0, "support": 85000.0,
            "resistance": 95000.0, "sma": 88000.0, "trend": "yükseliş",
            "volatility_daily_stddev": 0.02, "distance_to_support_pct": 0.058,
            "is_above_support": True, "is_near_support": False,
            "distance_to_resistance_pct": 0.052, "is_near_resistance": False,
            "observed_at": _now_iso(),
        })
        _seed_outflow_event(db, amount=15_000_000)

        candidates = signal.generate_candidates(db)

    accumulation = next(c for c in candidates if c["direction"] == "accumulation")
    assert accumulation["components"]["technical"] > 0.0
    assert "desteğinin üstünde" in " ".join(accumulation["rationale"])
    # a real technical score means the old fallback cap no longer applies --
    # confidence can legitimately exceed it now.
    assert accumulation["confidence"] > signal._MAX_CONFIDENCE_WITHOUT_TECHNICAL


def test_high_sentiment_contradicts_accumulation_and_zeroes_the_component(tmp_path):
    """Regression: the first two real signal candidates the scheduled
    observer produced both had Fear&Greed=71 ("Greed") and both awarded it
    full credit toward an accumulation candidate -- the component used to
    be unconditional. PROJECT-PLAN.md's own worked counter-example says
    crowded/greedy conditions should weaken, not support, a late entry."""
    with Storage(tmp_path / "t.db") as db:
        db.insert_market_snapshot({
            "symbol": "BTCUSDT", "funding_rate": 0.00005, "open_interest": 100.0,
            "mark_price": 90000.0, "observed_at": _now_iso(),
        })
        db.insert_sentiment_snapshot({
            "source": "fear_greed", "value": 71.0, "label": "Greed",
            "raw_json": {}, "observed_at": _now_iso(),
        })
        _seed_outflow_event(db, amount=15_000_000)

        candidates = signal.generate_candidates(db)

    accumulation = next(c for c in candidates if c["direction"] == "accumulation")
    assert accumulation["components"]["sentiment"] == 0.0
    assert "çelişiyor" in " ".join(accumulation["rationale"])


def test_high_sentiment_corroborates_distribution(tmp_path):
    with Storage(tmp_path / "t.db") as db:
        db.insert_market_snapshot({
            "symbol": "BTCUSDT", "funding_rate": 0.00005, "open_interest": 100.0,
            "mark_price": 90000.0, "observed_at": _now_iso(),
        })
        db.insert_sentiment_snapshot({
            "source": "fear_greed", "value": 71.0, "label": "Greed",
            "raw_json": {}, "observed_at": _now_iso(),
        })
        _seed_inflow_event(db, amount=15_000_000)

        candidates = signal.generate_candidates(db)

    distribution = next(c for c in candidates if c["direction"] == "distribution")
    assert distribution["components"]["sentiment"] == 0.15
    assert "tutarlı" in " ".join(distribution["rationale"])


def test_low_sentiment_corroborates_accumulation(tmp_path):
    with Storage(tmp_path / "t.db") as db:
        db.insert_market_snapshot({
            "symbol": "BTCUSDT", "funding_rate": 0.00005, "open_interest": 100.0,
            "mark_price": 90000.0, "observed_at": _now_iso(),
        })
        db.insert_sentiment_snapshot({
            "source": "fear_greed", "value": 20.0, "label": "Extreme Fear",
            "raw_json": {}, "observed_at": _now_iso(),
        })
        _seed_outflow_event(db, amount=15_000_000)

        candidates = signal.generate_candidates(db)

    accumulation = next(c for c in candidates if c["direction"] == "accumulation")
    assert accumulation["components"]["sentiment"] == 0.15
    assert "tutarlı" in " ".join(accumulation["rationale"])


def test_price_below_support_zeroes_technical_for_accumulation(tmp_path):
    with Storage(tmp_path / "t.db") as db:
        db.insert_market_snapshot({
            "symbol": "BTCUSDT", "funding_rate": 0.00005, "open_interest": 100.0,
            "mark_price": 90000.0, "observed_at": _now_iso(),
        })
        db.insert_technical_snapshot({
            "symbol": "BTCUSDT", "current_price": 80000.0, "support": 85000.0,
            "resistance": 95000.0, "sma": 88000.0, "trend": "düşüş",
            "volatility_daily_stddev": 0.02, "distance_to_support_pct": -0.058,
            "is_above_support": False, "is_near_support": False,
            "distance_to_resistance_pct": 0.158, "is_near_resistance": False,
            "observed_at": _now_iso(),
        })
        _seed_outflow_event(db, amount=15_000_000)

        candidates = signal.generate_candidates(db)

    accumulation = next(c for c in candidates if c["direction"] == "accumulation")
    assert accumulation["components"]["technical"] == 0.0
    assert "ALTINDA" in " ".join(accumulation["rationale"])
