"""Single-file local SQLite storage. No external database needed."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS onchain_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tx_hash TEXT NOT NULL,
    log_index INTEGER NOT NULL,
    block_number INTEGER NOT NULL,
    token TEXT NOT NULL,
    from_address TEXT NOT NULL,
    to_address TEXT NOT NULL,
    amount_usd_estimate REAL,
    raw_amount TEXT NOT NULL,
    from_known_exchange TEXT,
    to_known_exchange TEXT,
    observed_at TEXT NOT NULL,
    UNIQUE(tx_hash, log_index)
);
CREATE INDEX IF NOT EXISTS idx_onchain_block ON onchain_events(block_number);

CREATE TABLE IF NOT EXISTS event_classifications (
    tx_hash TEXT NOT NULL,
    log_index INTEGER NOT NULL,
    significance TEXT NOT NULL,
    interpretation TEXT NOT NULL,
    confidence REAL NOT NULL,
    classified_at TEXT NOT NULL,
    PRIMARY KEY (tx_hash, log_index)
);

CREATE TABLE IF NOT EXISTS scan_cursor (
    source TEXT PRIMARY KEY,
    last_block_scanned INTEGER NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS market_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    funding_rate REAL,
    open_interest REAL,
    mark_price REAL,
    observed_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_market_symbol_time ON market_snapshots(symbol, observed_at);

CREATE TABLE IF NOT EXISTS sentiment_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    value REAL NOT NULL,
    label TEXT,
    raw_json TEXT,
    observed_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS signal_candidates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    direction TEXT NOT NULL,
    confidence REAL NOT NULL,
    components_json TEXT NOT NULL,
    rationale_json TEXT NOT NULL,
    generated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS headlines (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    title TEXT NOT NULL,
    link TEXT NOT NULL UNIQUE,
    published_at TEXT,
    observed_at TEXT NOT NULL
);
"""


class Storage:
    """Thin wrapper over a single SQLite file. Not thread-safe by design --
    this is a single-process observer, not a concurrent service."""

    def __init__(self, db_path: str | Path) -> None:
        self.path = Path(db_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> Storage:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def insert_onchain_event(self, event: dict[str, Any]) -> bool:
        """Insert one on-chain transfer event. Returns False if it was a
        duplicate (same tx_hash + log_index), True if newly inserted."""
        try:
            self._conn.execute(
                """
                INSERT INTO onchain_events
                    (tx_hash, log_index, block_number, token, from_address, to_address,
                     amount_usd_estimate, raw_amount, from_known_exchange, to_known_exchange, observed_at)
                VALUES (:tx_hash, :log_index, :block_number, :token, :from_address, :to_address,
                        :amount_usd_estimate, :raw_amount, :from_known_exchange, :to_known_exchange, :observed_at)
                """,
                event,
            )
            self._conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False

    def get_scan_cursor(self, source: str) -> int | None:
        row = self._conn.execute(
            "SELECT last_block_scanned FROM scan_cursor WHERE source = ?", (source,)
        ).fetchone()
        return int(row["last_block_scanned"]) if row else None

    def set_scan_cursor(self, source: str, block_number: int, observed_at: str) -> None:
        self._conn.execute(
            """
            INSERT INTO scan_cursor (source, last_block_scanned, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(source) DO UPDATE SET last_block_scanned = excluded.last_block_scanned,
                                               updated_at = excluded.updated_at
            """,
            (source, block_number, observed_at),
        )
        self._conn.commit()

    def insert_market_snapshot(self, snapshot: dict[str, Any]) -> None:
        self._conn.execute(
            """
            INSERT INTO market_snapshots (symbol, funding_rate, open_interest, mark_price, observed_at)
            VALUES (:symbol, :funding_rate, :open_interest, :mark_price, :observed_at)
            """,
            snapshot,
        )
        self._conn.commit()

    def insert_sentiment_snapshot(self, snapshot: dict[str, Any]) -> None:
        payload = dict(snapshot)
        payload["raw_json"] = json.dumps(payload.get("raw_json"), ensure_ascii=False)
        self._conn.execute(
            """
            INSERT INTO sentiment_snapshots (source, value, label, raw_json, observed_at)
            VALUES (:source, :value, :label, :raw_json, :observed_at)
            """,
            payload,
        )
        self._conn.commit()

    def insert_signal_candidate(self, candidate: dict[str, Any]) -> None:
        self._conn.execute(
            """
            INSERT INTO signal_candidates (direction, confidence, components_json, rationale_json, generated_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                candidate["direction"], candidate["confidence"],
                json.dumps(candidate["components"], ensure_ascii=False),
                json.dumps(candidate["rationale"], ensure_ascii=False),
                candidate["generated_at"],
            ),
        )
        self._conn.commit()

    def insert_classification(self, tx_hash: str, log_index: int, classification: dict[str, Any], observed_at: str) -> None:
        self._conn.execute(
            """
            INSERT OR REPLACE INTO event_classifications
                (tx_hash, log_index, significance, interpretation, confidence, classified_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (tx_hash, log_index, classification["significance"], classification["interpretation"],
             classification["confidence"], observed_at),
        )
        self._conn.commit()

    def insert_headline(self, headline: dict[str, Any]) -> bool:
        """Insert one headline. Returns False if it was a duplicate (same
        link -- RSS feeds re-list recent items on every fetch, so this is
        the normal case, not an error), True if newly inserted."""
        try:
            self._conn.execute(
                """
                INSERT INTO headlines (source, title, link, published_at, observed_at)
                VALUES (:source, :title, :link, :published_at, :observed_at)
                """,
                headline,
            )
            self._conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False

    def recent_headlines(self, limit: int = 50) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM headlines ORDER BY observed_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(row) for row in rows]

    def recent_onchain_events(self, limit: int = 50) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM onchain_events ORDER BY block_number DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(row) for row in rows]

    def latest_market_snapshot(self, symbol: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM market_snapshots WHERE symbol = ? ORDER BY observed_at DESC LIMIT 1",
            (symbol,),
        ).fetchone()
        return dict(row) if row else None

    def latest_sentiment_snapshot(self, source: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM sentiment_snapshots WHERE source = ? ORDER BY observed_at DESC LIMIT 1",
            (source,),
        ).fetchone()
        return dict(row) if row else None
