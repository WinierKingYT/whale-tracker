"""Historical data fetchers for the backtest, all cached to
data/backtest-cache/ so a period is downloaded once, not per run.

Onchain flow is the expensive part and the reason caching is per-chunk:
signal.py's flow component only counts transfers to/from known,
non-DEX, non-flagged wallets, so instead of production's wide-net scan
(every Transfer, filtered client-side) this asks eth_getLogs for only
those addresses via topic filters. Measured before building: ~1-5s per
2000-5000 block query on the free public RPC, some intermittent errors
(hence retries), and the amount threshold still has to be applied
client-side since eth_getLogs can't filter on value. Only the >=min_usd
events are cached, so the cache stays small even though the download
isn't.

Needs an archive-capable RPC for anything older than ~1-2 days:
production's free keyless endpoint (publicnode) answers older
eth_getLogs with "Archive requests require a personal token", and every
other keyless public RPC probed on 2026-09-24 was either archive-less,
capped at 10-800 block ranges, or down. Set ARCHIVE_RPC_ENV to a free-
tier archive endpoint (e.g. Alchemy/Infura/publicnode personal token) --
read from the environment, never committed."""

from __future__ import annotations

import hashlib
import json
import os
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests

from whale_tracker.sources import onchain
from whale_tracker.sources._retry import get_with_retries

CACHE_DIR = Path(__file__).resolve().parents[3] / "data" / "backtest-cache"
BINANCE_FAPI = "https://fapi.binance.com"
FEAR_GREED_URL = "https://api.alternative.me/fng/"
_TIMEOUT_S = 30
DEFAULT_CHUNK_BLOCKS = 2000
_RPC_RETRIES = 6
# Courtesy pause between heavy eth_getLogs calls -- free-tier endpoints.
_RPC_PAUSE_S = 0.3
ARCHIVE_RPC_ENV = "WHALE_TRACKER_ARCHIVE_RPC_URL"
# ~3 days per cached chunk on the Alchemy path: small enough that an
# interrupted download loses little, large enough to keep file count low.
ALCHEMY_CHUNK_BLOCKS = 21_600
_ALCHEMY_WORKERS = 4


class ArchiveAccessError(RuntimeError):
    """The configured RPC can't serve historical logs for this range."""


def archive_rpc_url() -> str:
    return os.environ.get(ARCHIVE_RPC_ENV) or onchain.RPC_URL


def check_archive_access(block_number: int) -> None:
    """One tiny eth_getLogs at the oldest block the backtest needs, so a
    non-archive endpoint fails fast with an actionable message instead
    of a traceback deep inside the chunk loop."""
    try:
        onchain._rpc("eth_getLogs", [{
            "address": onchain.TRACKED_TOKENS[0][1], "topics": [onchain.TRANSFER_TOPIC],
            "fromBlock": hex(block_number), "toBlock": hex(block_number + 2),
        }], retries=2, url=archive_rpc_url())
    except onchain.OnchainScanError as error:
        raise ArchiveAccessError(
            f"RPC ({'ortam değişkeni' if os.environ.get(ARCHIVE_RPC_ENV) else 'varsayılan publicnode'}) "
            f"blok {block_number} için geçmiş log vermiyor. Arşiv erişimli bir RPC adresini "
            f"{ARCHIVE_RPC_ENV} ortam değişkenine koy (ör. ücretsiz Alchemy/Infura anahtarı)."
        ) from error


def _cached(name: str, fetch: Callable[[], Any], *, cache_dir: Path = CACHE_DIR) -> Any:
    path = cache_dir / name
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    data = fetch()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")
    return data


def _get_json(url: str, params: dict[str, Any]) -> Any:
    def _do_request() -> requests.Response:
        response = requests.get(url, params=params, timeout=_TIMEOUT_S)
        response.raise_for_status()
        return response

    return get_with_retries(_do_request).json()


def _to_ms(moment: datetime) -> int:
    return int(moment.timestamp() * 1000)


def fetch_klines(symbol: str, interval: str, start: datetime, end: datetime) -> list[list[Any]]:
    """Binance futures klines in [start, end), oldest first, paged."""
    def _fetch() -> list[list[Any]]:
        rows: list[list[Any]] = []
        cursor = _to_ms(start)
        end_ms = _to_ms(end)
        while cursor < end_ms:
            page = _get_json(f"{BINANCE_FAPI}/fapi/v1/klines", {
                "symbol": symbol, "interval": interval, "startTime": cursor, "endTime": end_ms - 1, "limit": 1500,
            })
            if not page:
                break
            rows.extend(page)
            cursor = int(page[-1][0]) + 1
        return rows

    return _cached(f"klines-{symbol}-{interval}-{_to_ms(start)}-{_to_ms(end)}.json", _fetch)


def fetch_funding_history(symbol: str, start: datetime, end: datetime) -> list[dict[str, Any]]:
    """Settled funding rates (every 8h) in [start, end), oldest first."""
    def _fetch() -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        cursor = _to_ms(start)
        end_ms = _to_ms(end)
        while cursor < end_ms:
            page = _get_json(f"{BINANCE_FAPI}/fapi/v1/fundingRate", {
                "symbol": symbol, "startTime": cursor, "endTime": end_ms - 1, "limit": 1000,
            })
            if not page:
                break
            rows.extend({"funding_time_ms": int(r["fundingTime"]), "rate": float(r["fundingRate"])} for r in page)
            cursor = int(page[-1]["fundingTime"]) + 1
        return rows

    return _cached(f"funding-{symbol}-{_to_ms(start)}-{_to_ms(end)}.json", _fetch)


def fetch_fear_greed_history() -> list[dict[str, Any]]:
    """Full daily Fear&Greed history, oldest first. Cached per UTC day
    since the endpoint always returns everything up to today."""
    def _fetch() -> list[dict[str, Any]]:
        payload = _get_json(FEAR_GREED_URL, {"limit": 0})
        entries = [
            {"timestamp": int(e["timestamp"]), "value": float(e["value"]), "label": str(e["value_classification"])}
            for e in payload["data"]
        ]
        return sorted(entries, key=lambda e: e["timestamp"])

    return _cached(f"fear-greed-{datetime.now(UTC).date().isoformat()}.json", _fetch)


def _block_timestamp(block_number: int) -> int:
    block = onchain._rpc("eth_getBlockByNumber", [hex(block_number), False], retries=_RPC_RETRIES)
    return int(block["timestamp"], 16)


def block_at_or_after(moment: datetime) -> int:
    """Smallest block whose timestamp is >= `moment` (binary search)."""
    target = int(moment.timestamp())
    low, high = 0, onchain.current_block_number()
    # Post-merge blocks are ~12s apart -- narrow the search window first
    # so the binary search is ~15 RPC calls, not ~25.
    estimate = high - (int(time.time()) - target) // 12
    low = max(0, estimate - 50_000)
    while _block_timestamp(low) > target and low > 0:
        low = max(0, low - 50_000)
    while low < high:
        mid = (low + high) // 2
        if _block_timestamp(mid) < target:
            low = mid + 1
        else:
            high = mid
    return low


def _flow_addresses() -> dict[str, str]:
    """Exactly the wallets signal._aggregate_exchange_flow counts:
    exchange-owned wallets only (no institutions, DEX, flagged)."""
    return onchain.exchange_wallets()


def _entity_types(from_addr: str, to_addr: str, labels: dict[str, str]) -> dict[str, str | None]:
    """`labels` is the exchange-only flow set, so membership IS the type."""
    return {
        "from_entity_type": onchain.ENTITY_EXCHANGE if from_addr.lower() in labels else None,
        "to_entity_type": onchain.ENTITY_EXCHANGE if to_addr.lower() in labels else None,
    }


def _events_from_logs(logs: list[dict[str, Any]], decimals: int, token: str, *, min_usd: float,
                      labels: dict[str, str]) -> list[dict[str, Any]]:
    events = []
    for log in logs:
        raw_amount = int(log["data"], 16)
        amount = raw_amount / (10**decimals)
        if amount < min_usd:
            continue
        from_addr = "0x" + log["topics"][1][-40:]
        to_addr = "0x" + log["topics"][2][-40:]
        events.append({
            "tx_hash": log["transactionHash"],
            "log_index": int(log["logIndex"], 16),
            "block_number": int(log["blockNumber"], 16),
            "block_timestamp": int(log["blockTimestamp"], 16),
            "token": token,
            "from_address": from_addr,
            "to_address": to_addr,
            "amount_usd_estimate": amount,
            "raw_amount": str(raw_amount),
            "from_known_exchange": labels.get(from_addr.lower()),
            "to_known_exchange": labels.get(to_addr.lower()),
            **_entity_types(from_addr, to_addr, labels),
        })
    return events


def _fetch_flow_chunk(from_block: int, to_block: int, *, min_usd: float, labels: dict[str, str]) -> list[dict[str, Any]]:
    padded = ["0x" + "0" * 24 + address[2:] for address in labels]
    events: dict[tuple[str, int], dict[str, Any]] = {}
    for token, contract, decimals in onchain.TRACKED_TOKENS:
        # Inflow (to = known wallet) and outflow (from = known wallet)
        # are separate queries; a transfer between two known wallets
        # shows up in both, so dedupe on (tx_hash, log_index).
        for topics in ([onchain.TRANSFER_TOPIC, None, padded], [onchain.TRANSFER_TOPIC, padded]):
            logs = onchain._rpc("eth_getLogs", [{
                "address": contract, "topics": topics, "fromBlock": hex(from_block), "toBlock": hex(to_block),
            }], retries=_RPC_RETRIES, url=archive_rpc_url())
            for event in _events_from_logs(logs, decimals, token, min_usd=min_usd, labels=labels):
                events[(event["tx_hash"], event["log_index"])] = event
            time.sleep(_RPC_PAUSE_S)
    return sorted(events.values(), key=lambda e: (e["block_number"], e["log_index"]))


def _uses_alchemy(url: str) -> bool:
    return urlparse(url).netloc.endswith("alchemy.com")


def _events_from_asset_transfers(
    transfers: list[dict[str, Any]], *, min_usd: float, labels: dict[str, str],
) -> list[dict[str, Any]]:
    token_by_contract = {contract.lower(): (symbol, decimals) for symbol, contract, decimals in onchain.TRACKED_TOKENS}
    events = []
    for transfer in transfers:
        token = token_by_contract.get(transfer["rawContract"]["address"].lower())
        if token is None:
            continue
        symbol, decimals = token
        raw_amount = int(transfer["rawContract"]["value"], 16)
        amount = raw_amount / (10**decimals)
        if amount < min_usd:
            continue
        from_addr = transfer["from"].lower()
        to_addr = (transfer["to"] or "").lower()
        block_time = datetime.fromisoformat(transfer["metadata"]["blockTimestamp"].replace("Z", "+00:00"))  # noqa: FURB162 -- keeps the explicit UTC intent
        events.append({
            "tx_hash": transfer["hash"],
            "log_index": int(transfer["uniqueId"].rsplit(":", 1)[1]),
            "block_number": int(transfer["blockNum"], 16),
            "block_timestamp": int(block_time.timestamp()),
            "token": symbol,
            "from_address": from_addr,
            "to_address": to_addr,
            "amount_usd_estimate": amount,
            "raw_amount": str(raw_amount),
            "from_known_exchange": labels.get(from_addr),
            "to_known_exchange": labels.get(to_addr),
            **_entity_types(from_addr, to_addr, labels),
        })
    return events


def _big_transfers_for(
    address: str, side: str, from_block: int, to_block: int, *, min_usd: float, labels: dict[str, str], url: str,
) -> list[dict[str, Any]]:
    """Every page of one wallet's transfers in one direction, filtered to
    >=min_usd page by page -- the busiest wallets move ~25K transfers a
    DAY, so the unfiltered list must never be held whole."""
    kept: list[dict[str, Any]] = []
    page_key = None
    while True:
        params: dict[str, Any] = {
            "fromBlock": hex(from_block), "toBlock": hex(to_block), side: address,
            "contractAddresses": [contract for _, contract, _ in onchain.TRACKED_TOKENS],
            "category": ["erc20"], "withMetadata": True, "excludeZeroValue": True,
            "maxCount": hex(1000), "order": "asc",
        }
        if page_key:
            params["pageKey"] = page_key
        result = onchain._rpc("alchemy_getAssetTransfers", [params], retries=_RPC_RETRIES, url=url)
        kept.extend(_events_from_asset_transfers(result["transfers"], min_usd=min_usd, labels=labels))
        page_key = result.get("pageKey")
        if not page_key:
            return kept


def _fetch_flow_chunk_alchemy(
    from_block: int, to_block: int, *, min_usd: float, labels: dict[str, str], url: str,
) -> list[dict[str, Any]]:
    """Alchemy's free tier caps eth_getLogs at a 10-block range (measured:
    ~86K calls for 30 days), but alchemy_getAssetTransfers has no range
    cap and pages 1000 transfers per call -- measured ~130 calls per day
    of history across all flow wallets."""
    jobs = [(address, side) for address in labels for side in ("fromAddress", "toAddress")]
    events: dict[tuple[str, int], dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=_ALCHEMY_WORKERS) as pool:
        batches = pool.map(
            lambda job: _big_transfers_for(job[0], job[1], from_block, to_block, min_usd=min_usd, labels=labels, url=url),
            jobs,
        )
        for batch in batches:
            for event in batch:
                events[(event["tx_hash"], event["log_index"])] = event
    return sorted(events.values(), key=lambda e: (e["block_number"], e["log_index"]))


def fetch_exchange_flow_events(
    start_block: int, end_block: int, *, min_usd: float = onchain.DEFAULT_MIN_USD,
    chunk_blocks: int | None = None, progress: Callable[[str], None] | None = None,
) -> list[dict[str, Any]]:
    """All >=min_usd USDT/USDC transfers to/from flow-counted wallets in
    [start_block, end_block], each chunk cached separately so an
    interrupted download resumes where it stopped. Uses Alchemy's
    asset-transfers API when the archive RPC is Alchemy, plain
    topic-filtered eth_getLogs otherwise."""
    url = archive_rpc_url()
    alchemy = _uses_alchemy(url)
    if chunk_blocks is None:
        chunk_blocks = ALCHEMY_CHUNK_BLOCKS if alchemy else DEFAULT_CHUNK_BLOCKS
    labels = _flow_addresses()
    # The queried address set IS the filter, so a changed wallet list
    # must not silently reuse chunks fetched against the old one.
    wallet_fingerprint = hashlib.sha1("".join(sorted(labels)).encode()).hexdigest()[:8]
    all_events: list[dict[str, Any]] = []
    # Chunks sit on absolute multiples of chunk_blocks, not relative to
    # this run's start, so a longer or later period reuses every chunk it
    # shares with an earlier run. A chunk cut short by end_block gets its
    # own (shorter) file name, so it can never be mistaken for the full
    # chunk later.
    chunk_starts = range((start_block // chunk_blocks) * chunk_blocks, end_block + 1, chunk_blocks)
    for index, chunk_start in enumerate(chunk_starts, 1):
        chunk_end = min(chunk_start + chunk_blocks - 1, end_block)
        name = f"flow-{wallet_fingerprint}/{chunk_start}-{chunk_end}-min{int(min_usd)}.json"
        if alchemy:
            fetch = lambda s=chunk_start, e=chunk_end: _fetch_flow_chunk_alchemy(
                s, e, min_usd=min_usd, labels=labels, url=url)
        else:
            fetch = lambda s=chunk_start, e=chunk_end: _fetch_flow_chunk(
                s, e, min_usd=min_usd, labels=labels)
        all_events.extend(_cached(name, fetch))
        if progress and (alchemy or index % 10 == 0 or index == len(chunk_starts)):
            progress(f"zincir üstü akış: {index}/{len(chunk_starts)} parça")
    return [e for e in all_events if start_block <= e["block_number"] <= end_block]
