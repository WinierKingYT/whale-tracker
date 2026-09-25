"""Single-file local SQLite storage. No external database needed."""

from __future__ import annotations

import json
import sqlite3
from bisect import bisect_right
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

# One observer cycle's market and technical fetches land seconds apart;
# the next cycle is 15 minutes later, so 5 minutes can't pair across cycles.
SAME_CYCLE_TOLERANCE = timedelta(minutes=5)

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
    from_entity_type TEXT,
    to_entity_type TEXT,
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

CREATE TABLE IF NOT EXISTS technical_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    current_price REAL,
    support REAL,
    resistance REAL,
    sma REAL,
    trend TEXT,
    volatility_daily_stddev REAL,
    distance_to_support_pct REAL,
    is_above_support INTEGER,
    is_near_support INTEGER,
    distance_to_resistance_pct REAL,
    is_near_resistance INTEGER,
    observed_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_technical_symbol_time ON technical_snapshots(symbol, observed_at);

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
    symbol TEXT NOT NULL DEFAULT 'BTCUSDT',
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

CREATE TABLE IF NOT EXISTS deep_analyses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    signal_candidate_id INTEGER NOT NULL REFERENCES signal_candidates(id),
    assessment TEXT NOT NULL,
    counter_argument TEXT NOT NULL,
    risk_flags_json TEXT NOT NULL,
    corroboration_strength TEXT NOT NULL,
    generated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS final_proposals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    signal_candidate_id INTEGER NOT NULL REFERENCES signal_candidates(id),
    action TEXT NOT NULL,
    reason TEXT,
    max_position_size_pct REAL NOT NULL,
    stop_loss_price REAL,
    entry_rationale TEXT,
    worst_case_scenario TEXT,
    counter_arguments_json TEXT NOT NULL,
    conviction TEXT,
    generated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS paper_positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    signal_candidate_id INTEGER NOT NULL REFERENCES signal_candidates(id),
    symbol TEXT NOT NULL DEFAULT 'BTCUSDT',
    entry_price REAL NOT NULL,
    stop_loss_price REAL NOT NULL,
    take_profit_price REAL NOT NULL,
    position_size_usd REAL NOT NULL,
    status TEXT NOT NULL,
    opened_at TEXT NOT NULL,
    closed_at TEXT,
    exit_price REAL,
    pnl_usd REAL,
    pnl_pct REAL
);
CREATE INDEX IF NOT EXISTS idx_paper_positions_status ON paper_positions(status);

CREATE TABLE IF NOT EXISTS ai_call_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    call_type TEXT NOT NULL,
    attempted INTEGER NOT NULL,
    succeeded INTEGER NOT NULL,
    duration_ms REAL NOT NULL,
    error_reason TEXT,
    called_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ai_call_log_type_time ON ai_call_log(call_type, called_at);

CREATE TABLE IF NOT EXISTS approval_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    signal_candidate_id INTEGER NOT NULL,
    symbol TEXT NOT NULL,
    entry_price REAL NOT NULL,
    stop_loss_price REAL NOT NULL,
    take_profit_price REAL NOT NULL,
    position_size_usd REAL NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    decided_at TEXT,
    note TEXT
);
CREATE INDEX IF NOT EXISTS idx_approval_requests_status ON approval_requests(status);
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
        self._migrate()

    def _migrate(self) -> None:
        """Additive, idempotent column migrations for DB files created
        before a column existed -- CREATE TABLE IF NOT EXISTS in SCHEMA
        only applies to brand-new tables, not columns added to an
        existing one (e.g. `symbol`, added when ETH support came in
        alongside the original BTC-only tables)."""
        for table, column, ddl in (
            ("signal_candidates", "symbol", "ALTER TABLE signal_candidates ADD COLUMN symbol TEXT NOT NULL DEFAULT 'BTCUSDT'"),
            ("paper_positions", "symbol", "ALTER TABLE paper_positions ADD COLUMN symbol TEXT NOT NULL DEFAULT 'BTCUSDT'"),
            # NULL on old rows: flow.py resolves those by address, fail-closed.
            ("onchain_events", "from_entity_type", "ALTER TABLE onchain_events ADD COLUMN from_entity_type TEXT"),
            ("onchain_events", "to_entity_type", "ALTER TABLE onchain_events ADD COLUMN to_entity_type TEXT"),
        ):
            existing_columns = {row["name"] for row in self._conn.execute(f"PRAGMA table_info({table})")}
            if column not in existing_columns:
                self._conn.execute(ddl)
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
                     amount_usd_estimate, raw_amount, from_known_exchange, to_known_exchange,
                     from_entity_type, to_entity_type, observed_at)
                VALUES (:tx_hash, :log_index, :block_number, :token, :from_address, :to_address,
                        :amount_usd_estimate, :raw_amount, :from_known_exchange, :to_known_exchange,
                        :from_entity_type, :to_entity_type, :observed_at)
                """,
                {"from_entity_type": None, "to_entity_type": None, **event},
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

    def insert_technical_snapshot(self, snapshot: dict[str, Any]) -> None:
        payload = dict(snapshot)
        payload["is_above_support"] = int(bool(payload["is_above_support"]))
        payload["is_near_support"] = int(bool(payload["is_near_support"]))
        payload["is_near_resistance"] = int(bool(payload["is_near_resistance"]))
        self._conn.execute(
            """
            INSERT INTO technical_snapshots
                (symbol, current_price, support, resistance, sma, trend,
                 volatility_daily_stddev, distance_to_support_pct, is_above_support, is_near_support,
                 distance_to_resistance_pct, is_near_resistance, observed_at)
            VALUES
                (:symbol, :current_price, :support, :resistance, :sma, :trend,
                 :volatility_daily_stddev, :distance_to_support_pct, :is_above_support, :is_near_support,
                 :distance_to_resistance_pct, :is_near_resistance, :observed_at)
            """,
            {k: v for k, v in payload.items() if k != "lookback_days"},
        )
        self._conn.commit()

    def latest_technical_snapshot(self, symbol: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM technical_snapshots WHERE symbol = ? ORDER BY observed_at DESC LIMIT 1",
            (symbol,),
        ).fetchone()
        if row is None:
            return None
        result = dict(row)
        result["is_above_support"] = bool(result["is_above_support"])
        result["is_near_support"] = bool(result["is_near_support"])
        result["is_near_resistance"] = bool(result["is_near_resistance"])
        return result

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

    def insert_signal_candidate(self, candidate: dict[str, Any]) -> int:
        cursor = self._conn.execute(
            """
            INSERT INTO signal_candidates (symbol, direction, confidence, components_json, rationale_json, generated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                candidate.get("symbol", "BTCUSDT"), candidate["direction"], candidate["confidence"],
                json.dumps(candidate["components"], ensure_ascii=False),
                json.dumps(candidate["rationale"], ensure_ascii=False),
                candidate["generated_at"],
            ),
        )
        self._conn.commit()
        return int(cursor.lastrowid)

    def insert_deep_analysis(self, signal_candidate_id: int, analysis: dict[str, Any], generated_at: str) -> None:
        self._conn.execute(
            """
            INSERT INTO deep_analyses
                (signal_candidate_id, assessment, counter_argument, risk_flags_json, corroboration_strength, generated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                signal_candidate_id, analysis["assessment"], analysis["counter_argument"],
                json.dumps(analysis["risk_flags"], ensure_ascii=False),
                analysis["corroboration_strength"], generated_at,
            ),
        )
        self._conn.commit()

    def insert_final_proposal(self, signal_candidate_id: int, proposal: dict[str, Any], generated_at: str) -> None:
        self._conn.execute(
            """
            INSERT INTO final_proposals
                (signal_candidate_id, action, reason, max_position_size_pct, stop_loss_price,
                 entry_rationale, worst_case_scenario, counter_arguments_json, conviction, generated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                signal_candidate_id, proposal["action"], proposal["reason"],
                proposal["max_position_size_pct"], proposal["stop_loss_price"],
                proposal["entry_rationale"], proposal["worst_case_scenario"],
                json.dumps(proposal["counter_arguments"], ensure_ascii=False),
                proposal["conviction"], generated_at,
            ),
        )
        self._conn.commit()

    def insert_paper_position(self, position: dict[str, Any]) -> int:
        payload = dict(position)
        payload.setdefault("symbol", "BTCUSDT")
        cursor = self._conn.execute(
            """
            INSERT INTO paper_positions
                (signal_candidate_id, symbol, entry_price, stop_loss_price, take_profit_price,
                 position_size_usd, status, opened_at)
            VALUES (:signal_candidate_id, :symbol, :entry_price, :stop_loss_price, :take_profit_price,
                    :position_size_usd, :status, :opened_at)
            """,
            payload,
        )
        self._conn.commit()
        return int(cursor.lastrowid)

    def open_paper_positions(self) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM paper_positions WHERE status = 'open' ORDER BY opened_at"
        ).fetchall()
        return [dict(row) for row in rows]

    def close_paper_position(
        self, position_id: int, *, exit_price: float, status: str, closed_at: str, pnl_usd: float, pnl_pct: float,
    ) -> None:
        self._conn.execute(
            """
            UPDATE paper_positions
            SET status = ?, closed_at = ?, exit_price = ?, pnl_usd = ?, pnl_pct = ?
            WHERE id = ?
            """,
            (status, closed_at, exit_price, pnl_usd, pnl_pct, position_id),
        )
        self._conn.commit()

    def all_paper_positions(self) -> list[dict[str, Any]]:
        rows = self._conn.execute("SELECT * FROM paper_positions ORDER BY opened_at").fetchall()
        return [dict(row) for row in rows]

    def insert_approval_request(self, request: dict[str, Any]) -> int:
        """Asama 5 skeleton (see approval.py) -- records that the system
        proposed a real-money trade and is waiting on a human decision.
        Never itself a trade; status starts 'pending' and only becomes
        'approved'/'rejected' via decide_approval_request, always by an
        explicit human action (approval.py's CLI), never automatically."""
        payload = dict(request)
        cursor = self._conn.execute(
            """
            INSERT INTO approval_requests
                (signal_candidate_id, symbol, entry_price, stop_loss_price, take_profit_price,
                 position_size_usd, status, created_at)
            VALUES (:signal_candidate_id, :symbol, :entry_price, :stop_loss_price, :take_profit_price,
                    :position_size_usd, :status, :created_at)
            """,
            payload,
        )
        self._conn.commit()
        return int(cursor.lastrowid)

    def pending_approval_requests(self) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM approval_requests WHERE status = 'pending' ORDER BY created_at"
        ).fetchall()
        return [dict(row) for row in rows]

    def get_approval_request(self, request_id: int) -> dict[str, Any] | None:
        row = self._conn.execute("SELECT * FROM approval_requests WHERE id = ?", (request_id,)).fetchone()
        return dict(row) if row else None

    def decide_approval_request(self, request_id: int, *, status: str, decided_at: str, note: str | None = None) -> None:
        self._conn.execute(
            "UPDATE approval_requests SET status = ?, decided_at = ?, note = ? WHERE id = ?",
            (status, decided_at, note, request_id),
        )
        self._conn.commit()

    def all_approval_requests(self) -> list[dict[str, Any]]:
        rows = self._conn.execute("SELECT * FROM approval_requests ORDER BY created_at").fetchall()
        return [dict(row) for row in rows]

    def insert_ai_call_log(
        self, call_type: str, *, attempted: int, succeeded: int, duration_ms: float,
        error_reason: str | None, called_at: str,
    ) -> None:
        """One row per AI call SITE per cycle (e.g. one row for the whole
        classify_top_events batch, not one row per individual event) --
        see observe.py for what gets logged where. Exists so status.py can
        answer "how much of the shared Hermes/Claude quota is this
        actually using" with real numbers instead of the one-time
        estimate from when Kademe 2 was first wired up."""
        self._conn.execute(
            """
            INSERT INTO ai_call_log (call_type, attempted, succeeded, duration_ms, error_reason, called_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (call_type, attempted, succeeded, duration_ms, error_reason, called_at),
        )
        self._conn.commit()

    def recent_ai_calls(self, call_type: str, *, limit: int) -> list[dict[str, Any]]:
        """Most recent `limit` logged calls for `call_type`, newest first --
        used by classify.py's circuit breaker to check for a run of
        consecutive failures without scanning the whole table."""
        rows = self._conn.execute(
            "SELECT * FROM ai_call_log WHERE call_type = ? ORDER BY called_at DESC, id DESC LIMIT ?",
            (call_type, limit),
        ).fetchall()
        return [dict(row) for row in rows]

    def ai_call_log_summary(self) -> list[dict[str, Any]]:
        """Per call_type: total cycles logged, total attempted/succeeded
        calls, average duration, and how many cycles had zero successes
        (a proxy for quota/rate-limit trouble -- see the 2026-09-23
        Kademe 2 blackout window found via this exact question)."""
        rows = self._conn.execute(
            """
            SELECT call_type,
                   COUNT(*) AS cycles,
                   SUM(attempted) AS attempted,
                   SUM(succeeded) AS succeeded,
                   AVG(duration_ms) AS avg_duration_ms,
                   SUM(CASE WHEN attempted > 0 AND succeeded = 0 THEN 1 ELSE 0 END) AS failed_cycles
            FROM ai_call_log
            GROUP BY call_type
            ORDER BY call_type
            """
        ).fetchall()
        return [dict(row) for row in rows]

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

    def price_and_levels_history(self, symbol: str) -> list[dict[str, Any]]:
        """Every cycle's mark price paired with that same cycle's support/
        resistance, oldest first -- backtest/baseline.py walks this to
        replay random entries under the exact exit rules the strategy's
        own positions got.

        Pairs each market snapshot with the latest technical snapshot up
        to SAME_CYCLE_TOLERANCE after it, not by equal timestamps: the
        simulator and backtest stamp both identically, but the live
        observer fetches technicals a second or two after the market
        snapshot, so an equality join matched 0 rows on real data."""
        markets = self._conn.execute(
            "SELECT observed_at, mark_price FROM market_snapshots WHERE symbol = ? ORDER BY observed_at", (symbol,),
        ).fetchall()
        technicals = self._conn.execute(
            "SELECT observed_at, support, resistance FROM technical_snapshots WHERE symbol = ? ORDER BY observed_at",
            (symbol,),
        ).fetchall()
        technical_times = [datetime.fromisoformat(row["observed_at"]) for row in technicals]
        history = []
        for market in markets:
            limit = datetime.fromisoformat(market["observed_at"]) + SAME_CYCLE_TOLERANCE
            index = bisect_right(technical_times, limit) - 1
            if index >= 0:
                history.append({
                    "observed_at": market["observed_at"], "mark_price": market["mark_price"],
                    "support": technicals[index]["support"], "resistance": technicals[index]["resistance"],
                })
        return history

    def market_snapshot_near(self, symbol: str, timestamp: str) -> dict[str, Any] | None:
        """The snapshot at-or-before `timestamp`, falling back to the
        earliest available snapshot if none exists that early -- used for
        "what was the price around period start" (evaluation.py's
        BTC-hold comparison), where the exact observe.py cycle boundary
        rarely lines up with a position's own opened_at."""
        row = self._conn.execute(
            "SELECT * FROM market_snapshots WHERE symbol = ? AND observed_at <= ? ORDER BY observed_at DESC LIMIT 1",
            (symbol, timestamp),
        ).fetchone()
        if row is None:
            row = self._conn.execute(
                "SELECT * FROM market_snapshots WHERE symbol = ? ORDER BY observed_at ASC LIMIT 1", (symbol,)
            ).fetchone()
        return dict(row) if row else None

    def latest_sentiment_snapshot(self, source: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM sentiment_snapshots WHERE source = ? ORDER BY observed_at DESC LIMIT 1",
            (source,),
        ).fetchone()
        return dict(row) if row else None
