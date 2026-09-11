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
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL;")
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
        if event.model_fields.get("type") and payload["type"] == "position":
            self._prune_positions()
        return True

    def _prune_positions(self) -> None:
        cutoff = time.time() - self.retention_s
        self._conn.execute(
            "DELETE FROM events WHERE type='position' AND ts < ?", (cutoff,)
        )

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

    def close(self) -> None:
        self._conn.close()


def _now_iso() -> str:
    import datetime

    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="milliseconds")
