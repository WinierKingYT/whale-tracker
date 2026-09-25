"""The one exchange-flow inclusion rule, shared by live signal, digest,
simulation and backtest so they can never drift apart again.

A side of a transfer counts only when its entity type is "exchange".
Institutions (funds, investment managers), DEX contracts, flagged and
unknown addresses never count. The type is read from the event's
`*_entity_type` field when present; rows stored before that column
existed are resolved by ADDRESS against the current wallet registry --
never by parsing the display label -- and anything unresolvable is
treated as non-exchange (fail-closed)."""

from __future__ import annotations

from typing import Any

from whale_tracker.sources.onchain import ENTITY_EXCHANGE, load_wallet_registry


def side_entity_type(event: dict[str, Any], side: str, registry: dict[str, tuple[str, str]] | None = None) -> str | None:
    kind = event.get(f"{side}_entity_type")
    if kind:
        return kind
    address = (event.get(f"{side}_address") or "").lower()
    if not address:
        return None
    entry = (registry if registry is not None else load_wallet_registry()).get(address)
    return entry[1] if entry else None


def exchange_sides(event: dict[str, Any], registry: dict[str, tuple[str, str]] | None = None) -> tuple[bool, bool]:
    """(into_exchange, out_of_exchange) for one transfer. Pass `registry`
    when classifying many events so the wallet file is read once."""
    return (
        side_entity_type(event, "to", registry) == ENTITY_EXCHANGE,
        side_entity_type(event, "from", registry) == ENTITY_EXCHANGE,
    )


def exchange_flow_contribution(event: dict[str, Any], registry: dict[str, tuple[str, str]] | None = None) -> float:
    """+amount INTO an exchange, -amount OUT of one; exchange-to-exchange
    nets to zero, and a transfer with no exchange side contributes 0."""
    into, out_of = exchange_sides(event, registry)
    amount = event["amount_usd_estimate"]
    return (amount if into else 0.0) - (amount if out_of else 0.0)
