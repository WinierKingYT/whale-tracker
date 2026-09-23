from whale_tracker.report import render_report


def _event(**overrides):
    base = {
        "block_number": 100, "token": "USDT", "amount_usd_estimate": 1_000_000.0,
        "from_known_exchange": None, "to_known_exchange": None,
    }
    base.update(overrides)
    return base


def test_report_groups_events_by_category():
    events = [
        _event(to_known_exchange="⚠ FLAGGED: something bad"),
        _event(to_known_exchange="binance"),
        _event(from_known_exchange="DEX: Uniswap V4: Pool Manager"),
        _event(),  # unknown
    ]
    report = render_report(onchain_events=events, market_snapshot=None, sentiment_snapshot=None)

    assert "⚠ İşaretlenmiş (1)" in report
    assert "Bilinen borsa/kurum (1)" in report
    assert "Bilinmeyen cüzdanlar (1)" in report
    assert "DEX rutin trafiği (gürültü, özetlendi): 1 işlem" in report
    # DEX events are summarized, not itemized -- no "blok 100" line count
    # should exceed the 3 itemized categories (flagged + known + unknown = 3)
    assert report.count("blok 100:") == 3


def test_report_handles_empty_and_missing_sections():
    report = render_report(
        onchain_events=[], market_snapshot=None, sentiment_snapshot=None, headlines=None
    )
    assert "(veri yok)" in report
    assert "(bu turda eşik-üstü transfer yok)" in report
    assert "(bu turda yeni başlık yok)" in report
    assert "Sinyal adayları" not in report  # no section printed when there are none


def test_report_shows_signal_candidates_with_rationale():
    candidate = {
        "symbol": "BTCUSDT", "direction": "accumulation", "confidence": 0.62,
        "rationale": ["24s net borsa akışı: çıkış $15,000,000", "funding nötr (0.0050%)"],
    }
    report = render_report(
        onchain_events=[], market_snapshot=None, sentiment_snapshot=None,
        signal_candidates=[candidate],
    )
    assert "[BTCUSDT/accumulation] güven=0.62" in report
    assert "24s net borsa akışı: çıkış $15,000,000" in report


def test_report_shows_multiple_symbols_in_market_section():
    report = render_report(
        onchain_events=[], sentiment_snapshot=None,
        market_snapshots={
            "BTCUSDT": {"mark_price": 70000.0, "funding_rate": 0.0001, "open_interest": 1000.0},
            "ETHUSDT": {"mark_price": 3000.0, "funding_rate": 0.0002, "open_interest": 500.0},
        },
    )
    assert "BTCUSDT:" in report
    assert "ETHUSDT:" in report
    assert "$70,000.00" in report
    assert "$3,000.00" in report
