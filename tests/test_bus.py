import sqlite3
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
