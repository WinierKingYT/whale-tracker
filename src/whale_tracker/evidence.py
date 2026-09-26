"""Evidence freshness gate (WT-05.1 P0).

A decision may only be made on evidence that is current. When critical
evidence is missing or older than MAX_EVIDENCE_AGE, the outcome is an
explicit ABSTAIN: no candidate, no Kademe 2/3 call, no paper position,
no Aşama 5 approval. Writing "stale" into a notification is not enough --
a stale snapshot silently reused as if it were current is exactly the
failure this module exists to stop.

Critical evidence per symbol: the Binance market snapshot (always) and
the technical snapshot (when one exists -- its absence is already handled
by signal.py capping the score and proposal.py refusing without a stop
level; a PRESENT but stale one would feed wrong levels). The on-chain
scan's own success is checked per cycle by the caller (observe.py),
because a failed scan leaves the flow window silently incomplete rather
than old."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

ABSTAIN = "ABSTAIN"

# The observer runs every 15 minutes: one full cycle plus fetch slack.
# A snapshot older than this did not come from the current cycle.
MAX_EVIDENCE_AGE = timedelta(minutes=20)


def _age_problem(name: str, snapshot: dict[str, Any] | None, now: datetime, *, required: bool) -> str | None:
    if snapshot is None:
        return f"{name} verisi yok" if required else None
    observed = datetime.fromisoformat(snapshot["observed_at"])
    if observed.tzinfo is None:
        observed = observed.replace(tzinfo=UTC)
    age = now - observed
    if age > MAX_EVIDENCE_AGE:
        return f"{name} verisi bayat ({int(age.total_seconds() // 60)} dk > {int(MAX_EVIDENCE_AGE.total_seconds() // 60)} dk)"
    if age < -MAX_EVIDENCE_AGE:
        return f"{name} verisi gelecekten ({observed.isoformat()})"
    return None


def freshness_problems(storage: Any, symbol: str, *, now: datetime | None = None) -> list[str]:
    """Reasons to ABSTAIN for `symbol` based on stored evidence age; empty
    list means the evidence is fresh enough to decide on."""
    now = now or datetime.now(UTC)
    problems = [
        _age_problem("market", storage.latest_market_snapshot(symbol), now, required=True),
        _age_problem("technical", storage.latest_technical_snapshot(symbol), now, required=False),
    ]
    return [p for p in problems if p]
