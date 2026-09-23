"""On-chain stablecoin transfer scanner, Ethereum mainnet.

Design decisions from research/spikes (see docs/TECHNICAL-APPROACH.md and
docs/DATA-SOURCES.md), not guesses:

- "Wide net, not watch-list": we do NOT filter eth_getLogs by a known
  wallet as sender/recipient. A live spike found Binance's own labeled
  main wallet had zero USDT activity in a 7-hour window despite 7.7M
  lifetime transactions -- exchanges rotate which wallet is "active."
  Instead we pull every Transfer above the USD threshold and cross-
  reference both sides against data/known-exchange-wallets.json
  afterward. A transfer between two unknown wallets is still recorded
  (it may be a genuine unlabeled whale) but flagged as such.
- Small, incremental block ranges only. A spike found a wide unfiltered
  eth_getLogs call (50k+ blocks) times out on the free public RPC; this
  scanner is meant to run frequently (poll loop) and only ever asks for
  blocks since its own last checkpoint (storage.scan_cursor), which is a
  handful of blocks at Ethereum's ~12s block time.
- No API key: uses a free, keyless public RPC (ethereum-rpc.publicnode.com).
  A browser-like User-Agent header is required -- the endpoint 403s a
  bare Python urllib/requests default UA (confirmed empirically).
"""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import requests

RPC_URL = "https://ethereum-rpc.publicnode.com"
_TIMEOUT_S = 20
_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"

# (symbol, contract_address, decimals) -- verified against Etherscan during research.
TRACKED_TOKENS: tuple[tuple[str, str, int], ...] = (
    ("USDT", "0xdac17f958d2ee523a2206206994597c13d831ec7", 6),
    ("USDC", "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48", 6),
)

DEFAULT_MIN_USD = 1_000_000.0
# First-run fallback when no scan cursor exists yet: don't backfill deep
# history (slow, and not what an observer needs) -- start a few blocks back.
DEFAULT_LOOKBACK_BLOCKS = 50

_WALLETS_PATH = Path(__file__).resolve().parents[3] / "data" / "known-exchange-wallets.json"


class OnchainScanError(RuntimeError):
    """Raised when the RPC call fails or returns an unexpected shape."""


def _rpc(method: str, params: list[Any], retries: int = 3) -> Any:
    payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    headers = {"Content-Type": "application/json", "User-Agent": _USER_AGENT}
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            response = requests.post(RPC_URL, json=payload, headers=headers, timeout=_TIMEOUT_S)
            response.raise_for_status()
            body = response.json()
            if "error" in body:
                raise OnchainScanError(f"RPC error for {method}: {body['error']}")
            return body["result"]
        except (requests.RequestException, OnchainScanError) as error:
            last_error = error
            if attempt < retries - 1:
                time.sleep(2 * (attempt + 1))
    raise OnchainScanError(f"RPC call failed after {retries} attempts: {method}") from last_error


def _load_known_wallets() -> dict[str, str]:
    """Return {lowercase_address: label} for every wallet in
    data/known-exchange-wallets.json -- both the 'exchanges' section and
    'notable_non_exchange_entities' (funds/institutions found via our own
    scan output; excluded_or_deferred entries have no addresses to load)."""
    if not _WALLETS_PATH.is_file():
        return {}
    payload = json.loads(_WALLETS_PATH.read_text(encoding="utf-8"))
    lookup: dict[str, str] = {}
    for exchange_name, entry in payload.get("exchanges", {}).items():
        for wallet in entry.get("wallets", []):
            lookup[wallet["address"].lower()] = exchange_name
    for entity in payload.get("notable_non_exchange_entities", {}).get("entities", []):
        lookup[entity["address"].lower()] = entity["label"]
    return lookup


def current_block_number() -> int:
    return int(_rpc("eth_blockNumber", []), 16)


def _fetch_transfers(token_address: str, from_block: int, to_block: int) -> list[dict[str, Any]]:
    return _rpc(
        "eth_getLogs",
        [{
            "address": token_address,
            "topics": [TRANSFER_TOPIC],
            "fromBlock": hex(from_block),
            "toBlock": hex(to_block),
        }],
    )


def scan_new_transfers(
    storage: Any,
    *,
    min_usd: float = DEFAULT_MIN_USD,
    cursor_key: str = "ethereum_stablecoins",
) -> list[dict[str, Any]]:
    """Scan blocks since the last checkpoint for large stablecoin transfers.
    Returns the list of newly-recorded events (empty list is normal --
    most polls find nothing above threshold)."""
    known_wallets = _load_known_wallets()
    latest = current_block_number()

    cursor = storage.get_scan_cursor(cursor_key)
    from_block = (cursor + 1) if cursor is not None else max(0, latest - DEFAULT_LOOKBACK_BLOCKS)
    if from_block > latest:
        return []  # already caught up

    observed_at = datetime.now(UTC).isoformat()
    new_events: list[dict[str, Any]] = []

    for symbol, token_address, decimals in TRACKED_TOKENS:
        logs = _fetch_transfers(token_address, from_block, latest)
        for log in logs:
            raw_amount = int(log["data"], 16)
            amount = raw_amount / (10**decimals)
            # Stablecoins are ~$1: treat amount as a direct USD estimate.
            # Not true for a de-peg event -- acceptable for an Observer-phase
            # threshold filter, not for anything downstream that needs precision.
            if amount < min_usd:
                continue
            from_addr = "0x" + log["topics"][1][-40:]
            to_addr = "0x" + log["topics"][2][-40:]
            event = {
                "tx_hash": log["transactionHash"],
                "log_index": int(log["logIndex"], 16),
                "block_number": int(log["blockNumber"], 16),
                "token": symbol,
                "from_address": from_addr,
                "to_address": to_addr,
                "amount_usd_estimate": amount,
                "raw_amount": str(raw_amount),
                "from_known_exchange": known_wallets.get(from_addr.lower()),
                "to_known_exchange": known_wallets.get(to_addr.lower()),
                "observed_at": observed_at,
            }
            if storage.insert_onchain_event(event):
                new_events.append(event)

    storage.set_scan_cursor(cursor_key, latest, observed_at)
    return new_events
