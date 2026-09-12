import pytest

from storesmart.common.bus import EventBus
from storesmart.phase4_dwell.dwell import DwellTracker, classify_visit
from storesmart.phase4_dwell.heatmap import build_heatmap
from storesmart.phase4_dwell.run import _event_time


def make_bus(tmp_path):
    return EventBus(db_path=tmp_path / "test.db")


ZONES = {"Snacks": {"x": 0, "y": 0, "w": 10, "h": 10}}


def test_classify_visit_thresholds():
    assert classify_visit(1.0) == "passing"
    assert classify_visit(5.0) == "glance"
    assert classify_visit(15.0) == "engaged"


def test_dwell_emits_event_after_exit_debounce(tmp_path):
    bus = make_bus(tmp_path)
    tracker = DwellTracker(ZONES, enter_delay_s=1, exit_delay_s=1)
    tracker.update(1, (5, 5), now=0.0, bus=bus)   # inside zone, first sighting
    tracker.update(1, (5, 5), now=1.5, bus=bus)   # still inside past enter delay -> commits "Snacks"
    tracker.update(1, (50, 50), now=2.0, bus=bus)  # leaves zone, candidate=None starts
    tracker.update(1, (50, 50), now=3.5, bus=bus)  # past exit delay -> commits dwell event

    events = bus.recent(limit=10, event_type="dwell")
    assert len(events) == 1
    assert events[0]["zone"] == "Snacks"
    assert events[0]["dwell_s"] > 0


def test_dwell_ignores_brief_boundary_flicker(tmp_path):
    bus = make_bus(tmp_path)
    tracker = DwellTracker(ZONES, enter_delay_s=2, exit_delay_s=2)
    tracker.update(1, (5, 5), now=0.0, bus=bus)
    tracker.update(1, (50, 50), now=0.5, bus=bus)  # brief flicker out, before enter delay elapses
    tracker.update(1, (5, 5), now=0.8, bus=bus)    # back inside
    events = bus.recent(limit=10, event_type="dwell")
    assert events == []  # never committed to "Snacks" in the first place


def test_brief_excursion_outside_zone_does_not_emit_dwell(tmp_path):
    """Regression: committing an entry reset candidate_zone to None, which is
    also a real candidate ("outside every zone"), so the first sample taken
    outside the zone matched the stale candidate and committed the exit with
    no debounce — a 0.1s blip used to emit a dwell event."""
    bus = make_bus(tmp_path)
    tracker = DwellTracker(ZONES, enter_delay_s=2, exit_delay_s=2)
    tracker.update(1, (5, 5), now=0.0, bus=bus)    # enters the zone
    tracker.update(1, (5, 5), now=3.0, bus=bus)    # enter delay met -> commits "Snacks"
    tracker.update(1, (50, 50), now=3.1, bus=bus)  # 0.1s blip outside, well under exit_delay_s

    assert bus.recent(limit=10, event_type="dwell") == []

    tracker.update(1, (50, 50), now=5.5, bus=bus)  # now past the exit delay
    events = bus.recent(limit=10, event_type="dwell")
    assert len(events) == 1
    assert events[0]["zone"] == "Snacks"
    assert events[0]["dwell_s"] == 2.5  # 5.5 - entered_at 3.0


def test_remove_track_flushes_dwell_in_progress(tmp_path):
    """A track that stops being reported must still have its open dwell
    closed out, timed at the moment it was last actually seen."""
    bus = make_bus(tmp_path)
    tracker = DwellTracker(ZONES, enter_delay_s=1, exit_delay_s=1)
    tracker.update(1, (5, 5), now=0.0, bus=bus)
    tracker.update(1, (5, 5), now=2.0, bus=bus)  # commits "Snacks" at t=2.0

    tracker.remove_track(1, now=9.0, bus=bus)

    events = bus.recent(limit=10, event_type="dwell")
    assert len(events) == 1
    assert events[0]["zone"] == "Snacks"
    assert events[0]["dwell_s"] == 7.0  # 9.0 - 2.0, not the wall clock


def test_remove_track_outside_any_zone_emits_nothing(tmp_path):
    bus = make_bus(tmp_path)
    tracker = DwellTracker(ZONES, enter_delay_s=1, exit_delay_s=1)
    tracker.update(1, (50, 50), now=0.0, bus=bus)
    tracker.remove_track(1, now=5.0, bus=bus)
    assert bus.recent(limit=10, event_type="dwell") == []


def test_event_time_prefers_the_producers_timestamp():
    """Dwell must be measured in the timebase the positions were observed in,
    not in whenever Phase 4 happened to poll."""
    event = {"t": "2026-09-11T21:31:43.120+00:00", "type": "position"}
    assert _event_time(event, fallback=0.0) == pytest.approx(1789162303.120, abs=1e-3)


def test_event_time_falls_back_when_timestamp_is_unusable():
    assert _event_time({}, fallback=12.5) == 12.5
    assert _event_time({"t": "not-a-timestamp"}, fallback=12.5) == 12.5


def test_heatmap_suppresses_small_counts():
    positions = [
        {"x_ft": 1.2, "y_ft": 1.2, "track": 1},
        {"x_ft": 1.4, "y_ft": 1.4, "track": 2},
        {"x_ft": 9.0, "y_ft": 9.0, "track": 1},  # only 1 distinct track in this cell
    ]
    cells = build_heatmap(positions, grid_ft=1.0, k=2)
    assert (1, 1) in cells
    assert cells[(1, 1)] == 2
    assert (9, 9) not in cells
