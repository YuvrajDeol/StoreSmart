from storesmart.common.bus import EventBus
from storesmart.phase4_dwell.dwell import DwellTracker, classify_visit
from storesmart.phase4_dwell.heatmap import build_heatmap


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
