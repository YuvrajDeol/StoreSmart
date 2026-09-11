"""Shared event bus: a small SQLite (WAL mode) table that every module writes
events into via the schema gate, and that the dashboard reads from.

Only validated JSON events are ever written here — never frames or images.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Iterable, Optional

from storesmart.common.events import EventGate, RejectedEvent

DEFAULT_DB_PATH = Path("data/storesmart.db")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    cam TEXT,
    type TEXT NOT NULL,
    payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts);
CREATE INDEX IF NOT EXISTS idx_events_type ON events(type);

CREATE TABLE IF NOT EXISTS rejected_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    reason TEXT NOT NULL
);
"""


class EventBus:
    """Thread-safe writer/reader for the shared SQLite event log."""

    def __init__(self, db_path: Path | str = DEFAULT_DB_PATH, retention_s: float = 300.0):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.retention_s = retention_s
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False, timeout=10)
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.execute("PRAGMA busy_timeout=10000;")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()
        self.gate = EventGate()

    def emit(self, raw: dict) -> bool:
        """Validate and store one event. Returns True if accepted."""
        raw = dict(raw)
        raw.setdefault("t", _now_iso())
        try:
            event = self.gate.validate(raw)
        except RejectedEvent as exc:
            with self._lock:
                self._conn.execute(
                    "INSERT INTO rejected_events(ts, reason) VALUES (?, ?)",
                    (time.time(), exc.reason),
                )
                self._conn.commit()
            return False
        payload = event.model_dump(by_alias=True, exclude_none=True)
        with self._lock:
            self._conn.execute(
                "INSERT INTO events(ts, cam, type, payload) VALUES (?, ?, ?, ?)",
                (time.time(), payload.get("cam"), payload["type"], json.dumps(payload)),
            )
            self._conn.commit()
        if payload["type"] == "position":
            self._prune_positions()
        return True

    def _prune_positions(self) -> None:
        # Must hold the lock and commit: an uncommitted DELETE leaves this
        # connection's write transaction open, which blocks every other
        # process writing to the bus until the next emit() happens to commit
        # it (Phase 4 used to die with "database is locked" because of this).
        cutoff = time.time() - self.retention_s
        with self._lock:
            self._conn.execute(
                "DELETE FROM events WHERE type='position' AND ts < ?", (cutoff,)
            )
            self._conn.commit()

    def recent(self, limit: int = 50, event_type: Optional[str] = None) -> list[dict]:
        with self._lock:
            if event_type:
                rows = self._conn.execute(
                    "SELECT ts, payload FROM events WHERE type=? ORDER BY id DESC LIMIT ?",
                    (event_type, limit),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT ts, payload FROM events ORDER BY id DESC LIMIT ?", (limit,)
                ).fetchall()
        return [json.loads(p) for _, p in rows]

    def counts(self) -> dict:
        with self._lock:
            total = self._conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
            bytes_ = self._conn.execute(
                "SELECT COALESCE(SUM(LENGTH(payload)), 0) FROM events"
            ).fetchone()[0]
            rejected = self._conn.execute("SELECT COUNT(*) FROM rejected_events").fetchone()[0]
        return {"accepted": total, "rejected": rejected, "bytes": bytes_}

    def since(self, ts: float, event_type: Optional[str] = None) -> list[dict]:
        with self._lock:
            if event_type:
                rows = self._conn.execute(
                    "SELECT payload FROM events WHERE ts > ? AND type=? ORDER BY id",
                    (ts, event_type),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT payload FROM events WHERE ts > ? ORDER BY id", (ts,)
                ).fetchall()
        return [json.loads(p) for (p,) in rows]

    def since_id(self, last_id: int, event_type: Optional[str] = None) -> list[tuple[int, dict]]:
        """Events newer than `last_id`, as (row id, payload) pairs.

        Prefer this over `since()` for a polling consumer. `ts` is stamped by
        `emit()` *before* the row is inserted and committed, so a row can
        become visible carrying a `ts` that a reader has already advanced
        past — a timestamp cursor therefore drops events (and, depending on
        where the cursor is taken, replays them). Row ids come from SQLite's
        AUTOINCREMENT and become visible atomically with the commit, so an id
        cursor delivers every event exactly once, in insert order.
        """
        with self._lock:
            if event_type:
                rows = self._conn.execute(
                    "SELECT id, payload FROM events WHERE id > ? AND type=? ORDER BY id",
                    (last_id, event_type),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT id, payload FROM events WHERE id > ? ORDER BY id", (last_id,)
                ).fetchall()
        return [(row_id, json.loads(p)) for row_id, p in rows]

    def latest_id(self) -> int:
        """Highest row id currently in the log — the seed for a `since_id`
        cursor when a consumer should skip whatever is already there rather
        than replay it."""
        with self._lock:
            row = self._conn.execute("SELECT COALESCE(MAX(id), 0) FROM events").fetchone()
        return row[0]

    def close(self) -> None:
        self._conn.close()


def _now_iso() -> str:
    import datetime

    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="milliseconds")
