"""EventBus behaviour.

Two suites kept side by side: the bus's own contract (counts, retention,
prune-under-lock, timestamp readers) and the behaviour the Phase 2 -> Phase 4
integration depends on (concurrent writers must not lock each other out, and
a polling consumer must see every event exactly once).
"""
import sqlite3
import threading
import time

from storesmart.common.bus import EventBus


def test_accepted_and_rejected_counts(tmp_path):
    bus = EventBus(db_path=tmp_path / "t.db")
    assert bus.emit({"cam": "entrance", "type": "entry"}) is True
    assert bus.emit({"cam": "entrance", "type": "entry", "image_base64": "x" * 300}) is False
    counts = bus.counts()
    assert counts["accepted"] == 1
    assert counts["rejected"] == 1


def test_position_retention_prunes_old_rows(tmp_path):
    bus = EventBus(db_path=tmp_path / "t.db", retention_s=0.0, prune_every=2)
    for i in range(4):
        bus.emit({"cam": "floor", "type": "position", "x_ft": 1.0, "y_ft": 2.0, "track": i})
    # with retention_s=0 every prior position is already expired, so the prune
    # (which runs every 2 positions) must have cleared them out
    remaining = bus.recent(limit=50, event_type="position")
    assert len(remaining) < 4


def test_emit_leaves_no_open_write_transaction(tmp_path):
    """Regression test: the retention prune used to run outside the lock
    without committing, leaving a write transaction open and locking the
    database against every other process's writer."""
    db = tmp_path / "t.db"
    bus = EventBus(db_path=db, retention_s=0.0, prune_every=1)
    for i in range(3):
        bus.emit({"cam": "floor", "type": "position", "x_ft": 1.0, "y_ft": 2.0, "track": i})

    # a second, independent connection (as another module would have) must be
    # able to write immediately rather than hitting "database is locked"
    other = sqlite3.connect(db, timeout=2)
    other.execute("PRAGMA busy_timeout=2000;")
    other.execute("INSERT INTO events(ts, cam, type, payload) VALUES (?,?,?,?)",
                  (time.time(), "entrance", "entry", '{"type":"entry"}'))
    other.commit()
    other.close()


def test_last_ts_and_recent_with_ts(tmp_path):
    bus = EventBus(db_path=tmp_path / "t.db")
    assert bus.last_ts(event_type="entry") is None
    bus.emit({"cam": "entrance", "type": "entry"})
    ts = bus.last_ts(event_type="entry")
    assert ts is not None and abs(time.time() - ts) < 5
    rows = bus.recent_with_ts(limit=5, event_type="entry")
    assert len(rows) == 1
    assert rows[0][1]["type"] == "entry"


def _position(track: int) -> dict:
    return {"cam": "floor", "type": "position", "x_ft": 1.0, "y_ft": 2.0, "track": track}


def test_concurrent_writers_do_not_lock_each_other_out(tmp_path):
    """Regression: the retention prune ran its DELETE outside the lock and
    never committed, leaving the producer's write transaction open. The second
    process (Phase 4 emitting dwell) then died with 'database is locked'.
    prune_every=1 makes every position emit take the prune path, so this stays
    a real test of it now that the prune is batched."""
    db = tmp_path / "bus.db"
    producer, consumer = (EventBus(db_path=db, prune_every=1),
                          EventBus(db_path=db, prune_every=1))
    stop = threading.Event()
    produce_errors = []

    def produce():
        try:
            while not stop.is_set():
                for track in range(4):
                    producer.emit(_position(track))
                # The pause matters: it is what leaves the producer parked on
                # an open transaction in the unfixed code.
                stop.wait(0.05)
        except Exception as exc:  # pragma: no cover - only on regression
            produce_errors.append(exc)

    thread = threading.Thread(target=produce)
    thread.start()
    try:
        for _ in range(60):
            # Raises sqlite3.OperationalError("database is locked") if the
            # producer is holding an uncommitted transaction.
            consumer.emit({"cam": "floor", "type": "dwell", "zone": "Snacks", "dwell_s": 5.0})
            time.sleep(0.01)
    finally:
        stop.set()
        thread.join(timeout=5)

    assert produce_errors == []
    assert consumer.counts()["rejected"] == 0


def test_since_id_delivers_every_event_exactly_once(tmp_path):
    """A ts-based cursor drops events, because emit() stamps ts before the
    insert commits. Row ids become visible with the commit, so they don't."""
    db = tmp_path / "bus.db"
    writer, reader = EventBus(db_path=db), EventBus(db_path=db)
    n = 200
    cursor = reader.latest_id()
    done = threading.Event()

    def produce():
        for track in range(n):
            writer.emit(_position(track))
        done.set()

    thread = threading.Thread(target=produce)
    thread.start()
    seen = []
    while True:
        finished = done.is_set()
        for row_id, event in reader.since_id(cursor, event_type="position"):
            cursor = row_id
            seen.append(event["track"])
        if finished:
            break
    thread.join(timeout=5)

    # Exact equality catches all three failure modes at once: gaps, duplicates
    # and reordering.
    assert seen == list(range(n))


def test_latest_id_seeds_cursor_past_existing_backlog(tmp_path):
    bus = EventBus(db_path=tmp_path / "bus.db")
    bus.emit(_position(1))
    cursor = bus.latest_id()

    assert bus.since_id(cursor, event_type="position") == []

    bus.emit(_position(2))
    fresh = bus.since_id(cursor, event_type="position")
    assert [event["track"] for _, event in fresh] == [2]


def test_since_id_filters_by_event_type(tmp_path):
    bus = EventBus(db_path=tmp_path / "bus.db")
    cursor = bus.latest_id()
    bus.emit(_position(1))
    bus.emit({"cam": "floor", "type": "dwell", "zone": "Snacks", "dwell_s": 5.0})
    bus.emit(_position(2))

    positions = bus.since_id(cursor, event_type="position")
    assert [event["track"] for _, event in positions] == [1, 2]
    assert len(bus.since_id(cursor)) == 3
