"""Offline unit tests: mock the RPC layer, no real network calls.
End-to-end behavior against the real chain was verified manually during
development (see docs/TECHNICAL-APPROACH.md) -- these tests cover the
decoding/filtering/dedup logic deterministically."""


import pytest

from whale_tracker.sources import onchain
from whale_tracker.storage import Storage

USDT = onchain.TRACKED_TOKENS[0][1]


def _log(*, block_hex, tx_hash, log_index_hex, from_addr, to_addr, raw_amount):
    padded_from = "0x" + "0" * 24 + from_addr[2:]
    padded_to = "0x" + "0" * 24 + to_addr[2:]
    return {
        "address": USDT,
        "topics": [onchain.TRANSFER_TOPIC, padded_from, padded_to],
        "data": hex(raw_amount),
        "transactionHash": tx_hash,
        "logIndex": log_index_hex,
        "blockNumber": block_hex,
    }


@pytest.fixture
def fake_wallets_file(tmp_path, monkeypatch):
    known = tmp_path / "known-exchange-wallets.json"
    known.write_text(
        '{"exchanges": {"binance": {"wallets": '
        '[{"label": "Binance", "address": "0x3f5ce5fbfe3e9af3971dd833d26ba9b5c936f0be"}]}}}',
        encoding="utf-8",
    )
    monkeypatch.setattr(onchain, "_WALLETS_PATH", known)
    return known


def test_scan_finds_large_transfer_and_tags_known_wallet(monkeypatch, tmp_path, fake_wallets_file):
    binance = "0x3f5ce5fbfe3e9af3971dd833d26ba9b5c936f0be"
    stranger = "0x1111111111111111111111111111111111111100"
    logs = [
        _log(block_hex="0x64", tx_hash="0xaaa", log_index_hex="0x0",
             from_addr=stranger, to_addr=binance, raw_amount=2_000_000 * 10**6),  # $2M, above threshold
        _log(block_hex="0x64", tx_hash="0xbbb", log_index_hex="0x1",
             from_addr=stranger, to_addr=stranger, raw_amount=500 * 10**6),  # $500, below threshold
    ]

    def fake_rpc(method, params, retries=3):
        if method == "eth_blockNumber":
            return "0x64"
        if method == "eth_getLogs":
            return logs if params[0]["address"] == USDT else []
        raise AssertionError(f"unexpected method {method}")

    monkeypatch.setattr(onchain, "_rpc", fake_rpc)

    with Storage(tmp_path / "test.db") as db:
        events = onchain.scan_new_transfers(db, min_usd=1_000_000)

    assert len(events) == 1
    assert events[0]["amount_usd_estimate"] == 2_000_000.0
    assert events[0]["to_known_exchange"] == "binance"
    assert events[0]["from_known_exchange"] is None


def test_scan_is_idempotent_via_cursor(monkeypatch, tmp_path, fake_wallets_file):
    call_count = {"n": 0}

    def fake_rpc(method, params, retries=3):
        call_count["n"] += 1
        if method == "eth_blockNumber":
            return "0x64"
        if method == "eth_getLogs":
            from_block = int(params[0]["fromBlock"], 16)
            # Only the FIRST scan window (starting near block 0x64 - lookback) has data.
            if from_block <= 0x64 - onchain.DEFAULT_LOOKBACK_BLOCKS + 1:
                return [_log(block_hex="0x64", tx_hash="0xccc", log_index_hex="0x0",
                              from_addr="0x2222222222222222222222222222222222222200",
                              to_addr="0x3333333333333333333333333333333333333300",
                              raw_amount=5_000_000 * 10**6)]
            return []
        raise AssertionError(f"unexpected method {method}")

    monkeypatch.setattr(onchain, "_rpc", fake_rpc)

    with Storage(tmp_path / "test.db") as db:
        first = onchain.scan_new_transfers(db, min_usd=1_000_000)
        assert len(first) == 1
        second = onchain.scan_new_transfers(db, min_usd=1_000_000)
        assert second == []  # cursor moved past the event; no re-scan of old blocks
        assert len(db.recent_onchain_events()) == 1  # not double-inserted
