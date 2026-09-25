"""WT-05.1 P0: exchange flow counts exchange-owned wallets only, decided by
an explicit entity type -- never by the display label."""

from datetime import UTC, datetime, timedelta

from whale_tracker import signal
from whale_tracker.backtest import history
from whale_tracker.flow import exchange_flow_contribution
from whale_tracker.sources import onchain
from whale_tracker.storage import Storage

ABRAXAS = "0xb99a2c4c1c4f1fc27150681b740396f6ce1cbcf5"
BINANCE = "0x3f5ce5fbfe3e9af3971dd833d26ba9b5c936f0be"
UNKNOWN = "0x" + "1" * 40


def _event(from_addr, to_addr, amount=1_000_000.0, **extra):
    return {"from_address": from_addr, "to_address": to_addr, "amount_usd_estimate": amount} | extra


def test_registry_types_come_from_the_file_section_not_the_label():
    registry = onchain.load_wallet_registry()
    assert registry[BINANCE][1] == onchain.ENTITY_EXCHANGE
    assert registry[ABRAXAS][1] == onchain.ENTITY_INSTITUTION
    kinds = {kind for _, kind in registry.values()}
    assert kinds <= set(onchain.ENTITY_TYPES)
    assert {onchain.ENTITY_DEX, onchain.ENTITY_FLAGGED} <= kinds


def test_institution_is_not_exchange_flow():
    registry = onchain.load_wallet_registry()
    assert exchange_flow_contribution(_event(UNKNOWN, ABRAXAS), registry) == 0.0
    assert exchange_flow_contribution(_event(ABRAXAS, UNKNOWN), registry) == 0.0
    assert exchange_flow_contribution(_event(UNKNOWN, BINANCE), registry) == 1_000_000.0
    assert exchange_flow_contribution(_event(BINANCE, UNKNOWN), registry) == -1_000_000.0


def test_dex_and_flagged_are_not_exchange_flow():
    registry = onchain.load_wallet_registry()
    for kind in (onchain.ENTITY_DEX, onchain.ENTITY_FLAGGED):
        address = next(a for a, (_, k) in registry.items() if k == kind)
        assert exchange_flow_contribution(_event(UNKNOWN, address), registry) == 0.0


def test_a_label_that_looks_like_an_exchange_is_not_enough():
    event = _event(UNKNOWN, UNKNOWN, to_known_exchange="binance")
    assert exchange_flow_contribution(event, onchain.load_wallet_registry()) == 0.0


def test_legacy_rows_without_type_resolve_by_address_and_exclude_institutions(tmp_path):
    now = datetime.now(UTC)
    with Storage(tmp_path / "legacy.db") as db:
        for i, (src, dst, label) in enumerate([(UNKNOWN, ABRAXAS, "Abraxas"), (UNKNOWN, BINANCE, "binance")]):
            db.insert_onchain_event({
                "tx_hash": f"0x{i}", "log_index": 0, "block_number": i, "token": "USDT",
                "from_address": src, "to_address": dst, "amount_usd_estimate": 3e6, "raw_amount": "1",
                "from_known_exchange": None, "to_known_exchange": label,
                "observed_at": (now - timedelta(hours=1)).isoformat(),
            })
        flow = signal._aggregate_exchange_flow(db, hours=24, now=now)
    assert flow == {"inflow_usd": 3e6, "outflow_usd": 0.0, "net_inflow_usd": 3e6}


def test_live_scanner_tags_institutions_as_institution():
    event = onchain.tag_event({"from_address": ABRAXAS, "to_address": BINANCE}, onchain.load_wallet_registry())
    assert event["from_entity_type"] == "institution"
    assert event["to_entity_type"] == "exchange"


def test_backtest_downloads_the_same_exchange_only_wallet_set():
    flow_set = history._flow_addresses()
    assert ABRAXAS not in flow_set
    assert BINANCE in flow_set
    assert set(flow_set) == set(onchain.exchange_wallets())
